import logging
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class SqlService:
    """
    Wrapper delle query verso traceability_rs (+ fallback prezzi su resetservices) per:
      - produzione per ordine/giorno (mese corrente)
      - ordini prodotti oggi (per check vs Excel)
      - destinatari email per l'alert ordini mancanti
      - prezzo unitario di fallback da resetservices (ordini "storici")
      - dettagli ordine (product code/name, quantita') per corpo email
    """

    def __init__(self, db_connection, phase_id: int = 142, production_start: str = "07:30"):
        self.db = db_connection
        self.phase_id = phase_id
        h, m = production_start.split(':')
        # Minuti da sottrarre per mappare ScanTimeStart -> ProductionDay:
        # un giorno produttivo inizia alle 07:30 e finisce alle 07:30 del giorno dopo,
        # quindi sottraendo 7h30 il DATE del risultato e' la data del giorno produttivo.
        self.production_shift_minutes = int(h) * 60 + int(m)

    def get_month_production(
        self, month_start_dt: datetime, cutoff_dt: datetime
    ) -> List[Tuple[str, date, int]]:
        """
        Ritorna list di tuple (OrderNumber, ProductionDay, Qty) per la fase configurata,
        aggregando le Scannings IsPass=1 per ordine e giorno produttivo.
        """
        query = f"""
        SELECT
            Orders.OrderNumber AS OrderNumber,
            CAST(DATEADD(MINUTE, -{self.production_shift_minutes}, Scannings.ScanTimeStart) AS DATE) AS ProductionDay,
            SUM(CASE WHEN Scannings.IsPass = 1 THEN 1 ELSE 0 END) AS Qty
        FROM Traceability_rs.dbo.Scannings
        INNER JOIN Traceability_rs.dbo.OrderPhases
            ON Scannings.IDOrderPhase = OrderPhases.IDOrderPhase
        INNER JOIN Traceability_rs.dbo.Orders
            ON OrderPhases.IDOrder = Orders.IDOrder
        INNER JOIN Traceability_rs.dbo.Phases
            ON OrderPhases.IDPhase = Phases.IDPhase
        WHERE Phases.IDPhase = ?
            AND Scannings.ScanTimeStart >= ?
            AND Scannings.ScanTimeStart < ?
        GROUP BY
            Orders.OrderNumber,
            CAST(DATEADD(MINUTE, -{self.production_shift_minutes}, Scannings.ScanTimeStart) AS DATE)
        HAVING SUM(CASE WHEN Scannings.IsPass = 1 THEN 1 ELSE 0 END) > 0
        """
        conn = self.db.connect()
        with conn.cursor() as cursor:
            cursor.execute(query, self.phase_id, month_start_dt, cutoff_dt)
            rows = cursor.fetchall()

        result: List[Tuple[str, date, int]] = []
        for r in rows:
            order = str(r[0]).strip() if r[0] is not None else ""
            prod_day = r[1]
            if isinstance(prod_day, datetime):
                prod_day = prod_day.date()
            qty = int(r[2]) if r[2] is not None else 0
            if order and qty > 0:
                result.append((order, prod_day, qty))
        return result

    def get_today_produced_orders(
        self, day_start_dt: datetime, day_end_dt: datetime
    ) -> List[str]:
        """
        Lista DISTINCT degli OrderNumber con produzione (IsPass indifferente, contiamo
        qualunque scansione) nel giorno produttivo corrente. Serve per confrontare
        con la mappa prezzi dell'Excel.
        """
        query = """
        SELECT DISTINCT Orders.OrderNumber
        FROM Traceability_rs.dbo.Scannings
        INNER JOIN Traceability_rs.dbo.OrderPhases
            ON Scannings.IDOrderPhase = OrderPhases.IDOrderPhase
        INNER JOIN Traceability_rs.dbo.Orders
            ON OrderPhases.IDOrder = Orders.IDOrder
        INNER JOIN Traceability_rs.dbo.Phases
            ON OrderPhases.IDPhase = Phases.IDPhase
        WHERE Phases.IDPhase = ?
            AND Scannings.ScanTimeStart >= ?
            AND Scannings.ScanTimeStart < ?
        """
        conn = self.db.connect()
        with conn.cursor() as cursor:
            cursor.execute(query, self.phase_id, day_start_dt, day_end_dt)
            rows = cursor.fetchall()
        return [str(r[0]).strip() for r in rows if r[0]]

    def get_price_from_resetservices(self, order_number: str) -> Optional[float]:
        """
        Fallback prezzo unitario da resetservices quando l'ordine non e' nel file Excel
        (tipicamente ordini gia' chiusi/appartenenti al passato).
        Ritorna None se non trovato o se il valore non e' numerico.
        """
        query = """
        SELECT TOP 1 so.valuni AS ValUni
        FROM resetservices.dbo.TbSubOrdine so
        INNER JOIN resetservices.dbo.tbordini o
            ON so.IdOrdine = o.IdOrdine
        WHERE o.po = ?
        """
        try:
            conn = self.db.connect()
            with conn.cursor() as cursor:
                cursor.execute(query, order_number)
                row = cursor.fetchone()
        except Exception as e:
            logger.error(f"Errore query fallback prezzo per {order_number}: {e}")
            return None

        if not row or row[0] is None:
            return None
        try:
            return float(row[0])
        except (ValueError, TypeError):
            return None

    def get_order_details(self, order_number: str) -> Dict:
        """
        Dettagli ordine per il corpo email (order number, quantita', product code/name).
        """
        query = """
        SELECT o.ordernumber, o.OrderQuantity, p.productcode, p.productname
        FROM traceability_rs.dbo.Orders o
        INNER JOIN traceability_rs.dbo.Products p
            ON o.idproduct = p.idproduct
        WHERE o.OrderNumber = ?
        """
        try:
            conn = self.db.connect()
            with conn.cursor() as cursor:
                cursor.execute(query, order_number)
                row = cursor.fetchone()
        except Exception as e:
            logger.error(f"Errore query dettagli ordine {order_number}: {e}")
            row = None

        if not row:
            return {
                'orderNumber': order_number,
                'quantity': 0,
                'productCode': '',
                'productName': '',
            }
        return {
            'orderNumber': (str(row[0]).strip() if row[0] is not None else order_number),
            'quantity': int(row[1]) if row[1] is not None else 0,
            'productCode': (str(row[2]).strip() if row[2] is not None else ''),
            'productName': (str(row[3]).strip() if row[3] is not None else ''),
        }

    def get_semilavorato_labor_price(self, product_code: str) -> Optional[float]:
        """
        Recupera il costo unitario di SOLA MANODOPERA di un semilavorato dal vecchio ERP.
        Il pattern LIKE viene costruito dal product code rimuovendo tutto cio' che
        segue il primo '|' (incluso) e appendendo '%'.

        Es.: 'SL1234|ABC|X' -> 'SL1234%' ; 'SL9999' -> 'SL9999%'.
        """
        if not product_code:
            return None
        head = product_code.split('|')[0].strip()
        if not head:
            return None
        pattern = head + '%'

        query = """
        SELECT TOP 1 so.valuni
        FROM resetservices.dbo.tbsubordine so
        INNER JOIN resetservices.dbo.tbordini o
            ON o.idordine = so.idordine
        INNER JOIN resetservices.dbo.tbprodfin pf
            ON pf.idpf = so.idpf
        WHERE pf.EPICCode LIKE ?
            AND pf.BelongTo IS NULL
        ORDER BY so.ValUni DESC
        """
        try:
            conn = self.db.connect()
            with conn.cursor() as cursor:
                cursor.execute(query, pattern)
                row = cursor.fetchone()
        except Exception as e:
            logger.error(f"Errore query prezzo manodopera semilavorato '{product_code}' (pattern {pattern}): {e}")
            return None

        if not row or row[0] is None:
            return None
        try:
            return float(row[0])
        except (ValueError, TypeError):
            return None

    def get_orders_details_bulk(self, order_numbers: List[str]) -> Dict[str, Dict]:
        """
        Versione bulk di get_order_details: un'unica query con IN (...).
        """
        if not order_numbers:
            return {}
        placeholders = ','.join(['?'] * len(order_numbers))
        query = f"""
        SELECT o.ordernumber, o.OrderQuantity, p.productcode, p.productname
        FROM traceability_rs.dbo.Orders o
        INNER JOIN traceability_rs.dbo.Products p
            ON o.idproduct = p.idproduct
        WHERE o.OrderNumber IN ({placeholders})
        """
        try:
            conn = self.db.connect()
            with conn.cursor() as cursor:
                cursor.execute(query, *order_numbers)
                rows = cursor.fetchall()
        except Exception as e:
            logger.error(f"Errore query bulk dettagli ordini: {e}")
            return {}

        result: Dict[str, Dict] = {}
        for row in rows:
            if row[0] is None:
                continue
            order = str(row[0]).strip()
            result[order] = {
                'orderNumber': order,
                'quantity': int(row[1]) if row[1] is not None else 0,
                'productCode': (str(row[2]).strip() if row[2] is not None else ''),
                'productName': (str(row[3]).strip() if row[3] is not None else ''),
            }
        return result

    def get_missing_order_recipients(self) -> List[str]:
        """
        Legge 'sys_value_missing_Order' dalla tabella settings.
        """
        return self._get_settings_emails('sys_value_missing_Order')

    def get_daily_report_recipients(self) -> List[str]:
        """
        Legge 'Sys_email_production_intern' per il report giornaliero interno.
        """
        return self._get_settings_emails('Sys_email_production_intern')

    def _get_settings_emails(self, attribute: str) -> List[str]:
        query = """
        SELECT [VALUE]
        FROM traceability_rs.dbo.settings
        WHERE atribute = ?
        """
        try:
            conn = self.db.connect()
            with conn.cursor() as cursor:
                cursor.execute(query, attribute)
                rows = cursor.fetchall()
        except Exception as e:
            logger.error(f"Errore recupero destinatari per '{attribute}': {e}")
            return []

        emails: List[str] = []
        for row in rows:
            val = row[0]
            if not val:
                continue
            chunks = val.replace(';', ',').split(',')
            for e in chunks:
                e = e.strip()
                if e and '@' in e:
                    emails.append(e)
        return emails
