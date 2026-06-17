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
        Legge 'Sys_Email_Value_Report' dalla tabella settings.
        """
        return self._get_settings_emails('Sys_Email_Value_Report')

    def get_daily_report_recipients(self) -> List[str]:
        """
        Legge 'Sys_Email_Value_Report' per il report giornaliero interno.
        """
        return self._get_settings_emails('Sys_Email_Value_Report')

    def get_wip_report_recipients(self) -> List[str]:
        """
        Legge 'Sys_email_wip' dalla tabella settings.
        """
        return self._get_settings_emails('Sys_email_wip')

    def get_wip_by_day(self, start_date_str: str = "2026-01-01") -> List[Tuple[date, str, str, str, int, int]]:
        """
        Ritorna la lista degli ordini in WIP raggruppati per giorno di ingresso (PTH),
        con i conteggi di pezzi OK e FAIL:
        (ProductionDay, OrderNumber, ProductCode, ProductName, QtyOK, QtyFAIL)
        """
        query = """
        WITH WipBoards AS (
            SELECT 
                S.IDBoard, 
                OP.IDOrder,
                MIN(S.ScanTimeStart) AS WipEntryTime
            FROM Traceability_rs.dbo.Scannings S
            INNER JOIN Traceability_rs.dbo.OrderPhases OP ON S.IDOrderPhase = OP.IDOrderPhase
            INNER JOIN Traceability_rs.dbo.Orders O ON OP.IDOrder = O.IDOrder
            WHERE OP.IDPhase IN (3, 4, 141)
              AND S.IsPass = 1
              AND O.IsFinished = 0
              AND S.ScanTimeStart >= ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM Traceability_rs.dbo.Scannings S2
                  INNER JOIN Traceability_rs.dbo.OrderPhases OP2 ON S2.IDOrderPhase = OP2.IDOrderPhase
                  WHERE OP2.IDOrder = O.IDOrder
                    AND OP2.IDPhase = ?
                    AND S2.IDBoard = S.IDBoard
                    AND S2.IsPass = 1
              )
            GROUP BY S.IDBoard, OP.IDOrder
        ),
        LatestScans AS (
            SELECT 
                wb.IDBoard,
                wb.IDOrder,
                s.IsPass,
                ROW_NUMBER() OVER (PARTITION BY wb.IDBoard ORDER BY s.ScanTimeStart DESC, s.IDScan DESC) as rn
            FROM WipBoards wb
            INNER JOIN Traceability_rs.dbo.OrderPhases op ON wb.IDOrder = op.IDOrder
            INNER JOIN Traceability_rs.dbo.Scannings s ON op.IDOrderPhase = s.IDOrderPhase AND wb.IDBoard = s.IDBoard
        )
        SELECT
            CAST(DATEADD(MINUTE, -450, wb.WipEntryTime) AS DATE) AS ProductionDay,
            O.OrderNumber,
            P.ProductCode,
            P.ProductName,
            SUM(CASE WHEN ls.IsPass = 1 THEN 1 ELSE 0 END) AS QtyOK,
            SUM(CASE WHEN ls.IsPass = 0 THEN 1 ELSE 0 END) AS QtyFAIL
        FROM LatestScans ls
        INNER JOIN WipBoards wb ON ls.IDBoard = wb.IDBoard
        INNER JOIN Traceability_rs.dbo.Orders O ON wb.IDOrder = O.IDOrder
        INNER JOIN Traceability_rs.dbo.Products P ON O.IDProduct = P.IDProduct
        WHERE ls.rn = 1
        GROUP BY
            CAST(DATEADD(MINUTE, -450, wb.WipEntryTime) AS DATE),
            O.OrderNumber,
            P.ProductCode,
            P.ProductName
        ORDER BY ProductionDay DESC, O.OrderNumber ASC
        """
        conn = self.db.connect()
        with conn.cursor() as cursor:
            cursor.execute(query, start_date_str, self.phase_id)
            rows = cursor.fetchall()

        result = []
        for r in rows:
            prod_day = r[0]
            if isinstance(prod_day, datetime):
                prod_day = prod_day.date()
            order = str(r[1]).strip() if r[1] is not None else ""
            p_code = str(r[2]).strip() if r[2] is not None else ""
            p_name = str(r[3]).strip() if r[3] is not None else ""
            qty_ok = int(r[4]) if r[4] is not None else 0
            qty_fail = int(r[5]) if r[5] is not None else 0
            result.append((prod_day, order, p_code, p_name, qty_ok, qty_fail))
        return result

    def get_wip_details_bulk(self, start_date_str: str = "2026-01-01") -> List[Tuple[str, int, datetime, str, str, int]]:
        """
        Ritorna la lista dei dettagli analitici delle singole schede in WIP:
        (OrderNumber, IDBoard, ScanTimeStart, PhaseName, PhaseAbbreviation, IsPass)
        """
        query = """
        WITH WipBoards AS (
            SELECT DISTINCT S.IDBoard, OP.IDOrder
            FROM Traceability_rs.dbo.Scannings S
            INNER JOIN Traceability_rs.dbo.OrderPhases OP ON S.IDOrderPhase = OP.IDOrderPhase
            INNER JOIN Traceability_rs.dbo.Orders O ON OP.IDOrder = O.IDOrder
            WHERE OP.IDPhase IN (3, 4, 141)
              AND S.IsPass = 1
              AND O.IsFinished = 0
              AND S.ScanTimeStart >= ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM Traceability_rs.dbo.Scannings S2
                  INNER JOIN Traceability_rs.dbo.OrderPhases OP2 ON S2.IDOrderPhase = OP2.IDOrderPhase
                  WHERE OP2.IDOrder = O.IDOrder
                    AND OP2.IDPhase = ?
                    AND S2.IDBoard = S.IDBoard
                    AND S2.IsPass = 1
              )
        ),
        LatestScans AS (
            SELECT 
                wb.IDBoard,
                wb.IDOrder,
                s.ScanTimeStart,
                s.IsPass,
                p.PhaseName,
                p.PhaseAbbreviation,
                ROW_NUMBER() OVER (PARTITION BY wb.IDBoard ORDER BY s.ScanTimeStart DESC, s.IDScan DESC) as rn
            FROM WipBoards wb
            INNER JOIN Traceability_rs.dbo.OrderPhases op ON wb.IDOrder = op.IDOrder
            INNER JOIN Traceability_rs.dbo.Scannings s ON op.IDOrderPhase = s.IDOrderPhase AND wb.IDBoard = s.IDBoard
            INNER JOIN Traceability_rs.dbo.Phases p ON op.IDPhase = p.IDPhase
        )
        SELECT
            o.OrderNumber,
            ls.IDBoard,
            ls.ScanTimeStart,
            ls.PhaseName,
            ls.PhaseAbbreviation,
            ls.IsPass
        FROM LatestScans ls
        INNER JOIN Traceability_rs.dbo.Orders o ON ls.IDOrder = o.IDOrder
        WHERE ls.rn = 1
        ORDER BY o.OrderNumber ASC, ls.ScanTimeStart DESC
        """
        conn = self.db.connect()
        with conn.cursor() as cursor:
            cursor.execute(query, start_date_str, self.phase_id)
            rows = cursor.fetchall()

        result = []
        for r in rows:
            order = str(r[0]).strip() if r[0] is not None else ""
            board_id = int(r[1]) if r[1] is not None else 0
            scan_time = r[2]
            phase_name = str(r[3]).strip() if r[3] is not None else ""
            phase_abbr = str(r[4]).strip() if r[4] is not None else ""
            is_pass = int(r[5]) if r[5] is not None else 0
            result.append((order, board_id, scan_time, phase_name, phase_abbr, is_pass))
        return result

    def get_ytd_completed_production(self, start_date_dt: datetime, end_date_dt: datetime) -> List[Tuple[str, int]]:
        """
        Ritorna list di tuple (OrderNumber, Qty) per la fase 142 completata
        nel periodo YTD (dall'inizio dell'anno all'inizio del mese corrente).
        """
        query = """
        SELECT
            Orders.OrderNumber AS OrderNumber,
            SUM(CASE WHEN Scannings.IsPass = 1 THEN 1 ELSE 0 END) AS Qty
        FROM Traceability_rs.dbo.Scannings
        INNER JOIN Traceability_rs.dbo.OrderPhases
            ON Scannings.IDOrderPhase = OrderPhases.IDOrderPhase
        INNER JOIN Traceability_rs.dbo.Orders
            ON OrderPhases.IDOrder = Orders.IDOrder
        WHERE OrderPhases.IDPhase = ?
            AND Scannings.ScanTimeStart >= ?
            AND Scannings.ScanTimeStart < ?
        GROUP BY Orders.OrderNumber
        HAVING SUM(CASE WHEN Scannings.IsPass = 1 THEN 1 ELSE 0 END) > 0
        """
        conn = self.db.connect()
        with conn.cursor() as cursor:
            cursor.execute(query, self.phase_id, start_date_dt, end_date_dt)
            rows = cursor.fetchall()

        result: List[Tuple[str, int]] = []
        for r in rows:
            order = str(r[0]).strip() if r[0] is not None else ""
            qty = int(r[1]) if r[1] is not None else 0
            if order and qty > 0:
                result.append((order, qty))
        return result

    def _get_settings_emails(self, attribute: str) -> List[str]:
        import utils
        try:
            return utils.get_email_recipients(self.db.connect(), attribute)
        except Exception as e:
            logger.error(f"Errore recupero destinatari per '{attribute}' tramite utils: {e}")
            return []
