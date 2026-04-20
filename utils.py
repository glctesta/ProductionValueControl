from email_connector import EmailSender
import logging
import re
from typing import List, Optional
import os


logger = logging.getLogger("TraceabilityRS")  # usa la config fatta in main.py

def get_email_recipients(conn, attribute: str = 'Sys_Email_Purchase') -> List[str]:
    """
    Recupera gli indirizzi email dei destinatari dal database per lo specifico attributo.
    Esempi di attributo: 'Sys_Email_Purchase', 'Sys_email_submission'
    """
    try:
        query = """
        SELECT [VALUE]
        FROM traceability_rs.dbo.settings
        WHERE atribute = ?
        """
        with conn.cursor() as cursor:
            cursor.execute(query, attribute)
            results = cursor.fetchall()

        email_list = [row[0] for row in results if row[0]]

        valid_emails = []
        for email in email_list:
            chunks = []
            if ';' in email:
                chunks = [e.strip() for e in email.split(';')]
            elif ',' in email:
                chunks = [e.strip() for e in email.split(',')]
            else:
                chunks = [email.strip()]
            valid_emails.extend([e for e in chunks if e and '@' in e])

        logger.info(f"Indirizzi email trovati per {attribute}: {valid_emails}")
        return valid_emails

    except Exception as e:
        logger.error(f"Errore nel recupero degli indirizzi email ({attribute}): {str(e)}")
        raise





def send_email(
    recipients: List[str],
    subject: str,
    body: str,
    smtp_host: str = "vandewiele-com.mail.protection.outlook.com",
    smtp_port: int = 25,
    is_html: bool = False,  # <-- nuovo parametro opzionale, default False: compatibile
    timeout: int= 15,
    cc_emails: Optional[List[str]] = None,
    attachments: Optional[List] = None
) -> None:
    """
    Invia l'email ai destinatari specificati.

    Args:
        recipients: Lista di indirizzi email destinatari
        subject: Oggetto dell'email
        body: Corpo dell'email (testo o HTML se is_html=True)
        smtp_host: Host SMTP
        smtp_port: Porta SMTP
        is_html: Se True invia il corpo come HTML (default: False)

    Note: Usa EmailSender già presente nel progetto.
    :param timeout:
    """
    if not recipients:
        logger.error("Nessun destinatario specificato per l'email")
        return

    try:
        sender = EmailSender(smtp_host, smtp_port)

        # ATTENZIONE: credenziali hardcoded – idealmente spostarle in config sicura
        sender.save_credentials(
            "Accounting@Eutron.it",
            "9jHgFhSs7Vf+"
        )

        sender.send_email(
            to_email=', '.join(recipients),
            subject=subject,
            body=body,
            is_html=is_html,  # <-- passa il flag
            cc_emails=cc_emails,
            attachments=attachments
        )
        logger.info("Email inviata con successo a %d destinatari", len(recipients))
        print("email inviata")
    except Exception as e:
        logger.error("Errore nell'invio dell'email: %s", str(e))
        raise


def send_monthly_report_email(
    recipients: List[str],
    attachment_path: str,
    logo_path: str = "logo.png",
    smtp_host: str = "vandewiele-com.mail.protection.outlook.com",
    smtp_port: int = 25
) -> None:
    """
    Invia l'email mensile con il report Excel allegato e il logo aziendale.

    Args:
        recipients: Lista di indirizzi email destinatari
        attachment_path: Percorso completo del file Excel da allegare
        logo_path: Percorso del logo aziendale (default: logo.png nella directory corrente)
        smtp_host: Host SMTP
        smtp_port: Porta SMTP
    """
    if not recipients:
        logger.error("Nessun destinatario specificato per l'email mensile")
        return

    if not os.path.exists(attachment_path):
        logger.error(f"File allegato non trovato: {attachment_path}")
        raise FileNotFoundError(f"File allegato non trovato: {attachment_path}")

    try:
        sender = EmailSender(smtp_host, smtp_port)

        # Salva credenziali
        sender.save_credentials(
            "Accounting@Eutron.it",
            "9jHgFhSs7Vf+"
        )

        # Crea corpo HTML con logo embedded
        html_body = f"""
        <html>
        <body>
        <div style="font-family: Arial, sans-serif;">
            <div style="margin-bottom: 20px;">
                <img src="cid:company_logo" alt="Company Logo" width="200"/>
            </div>
            <h2 style="color: #366092;">Raport Lunar - Defecte după Validarea Plăcilor</h2>
            <p>Acest email rezumă situația referitoare la plăcile care au fost validate PASS pentru procesele de <strong>PTH</strong>, <strong>COATING</strong> și <strong>SMT</strong>.</p>
            <p>În atașament găsiți raportul detaliat cu statisticile <strong>PPM</strong> (Parts Per Million) pe utilizator.</p>
            <br/>
            <p style="color: #666;">
                Cu stimă,<br/>
                <strong>Sistem de Trasabilitate</strong>
            </p>
        </body>
        </html>
        """

        # Invia email con allegato
        sender.send_email(
            to_email=', '.join(recipients),
            subject="Monthly review - Fail after board validation",
            body=html_body,
            is_html=True,
            attachments=[attachment_path]
        )
        
        logger.info(f"Email mensile inviata con successo a {len(recipients)} destinatari")
        logger.info(f"Allegato: {os.path.basename(attachment_path)}")
        
    except Exception as e:
        logger.error(f"Errore nell'invio dell'email mensile: {str(e)}")
        raise


def send_npi_weekly_overview_email(
    recipients: List[str],
    attachment_path: str,
    summary: Optional[dict] = None,
    chart_path: Optional[str] = None,
    smtp_host: str = "vandewiele-com.mail.protection.outlook.com",
    smtp_port: int = 25
) -> None:
    """
    Invia l'email settimanale con il report NPI Overview in allegato.
    Se disponibile, include un grafico a torta inline con il riepilogo.
    """
    if not recipients:
        logger.error("Nessun destinatario specificato per l'email NPI settimanale")
        return

    if not os.path.exists(attachment_path):
        logger.error(f"File allegato non trovato: {attachment_path}")
        raise FileNotFoundError(f"File allegato non trovato: {attachment_path}")

    try:
        sender = EmailSender(smtp_host, smtp_port)
        sender.save_credentials("Accounting@Eutron.it", "9jHgFhSs7Vf+")

        summary = summary or {}
        total = summary.get('total', 0)
        active = summary.get('active', 0)
        in_completion = summary.get('in_completion', 0)
        completed = summary.get('completed', 0)
        overdue = summary.get('overdue', 0)

        chart_block = ""
        if chart_path:
            chart_block = """
            <div style="margin: 20px 0; text-align: center;">
                <img src="cid:npi_overview_pie" alt="NPI Overview Summary Chart" style="max-width: 520px; width: 100%; height: auto;">
            </div>
            """

        html_body = f"""
        <html>
        <body>
        <div style="font-family: Arial, sans-serif;">
            <h2 style="color: #366092;">Weekly NPI Overview Report</h2>
            <p>Please find attached the updated NPI Overview report, including the executive summary and detailed project tabs.</p>
            <p><strong>Summary snapshot:</strong></p>
            <ul>
                <li>Total Projects: {total}</li>
                <li>Active: {active}</li>
                <li>In Completion: {in_completion}</li>
                <li>Completed: {completed}</li>
                <li>Overdue: {overdue}</li>
            </ul>
            {chart_block}
            <p>This email is generated automatically by the NPI Project Management System.</p>
            <br/>
            <p style="color: #666;">
                Kind regards,<br/>
                <strong>NPI Project Management System</strong>
            </p>
        </div>
        </body>
        </html>
        """

        attachments = [attachment_path]
        if chart_path and os.path.exists(chart_path):
            attachments = [('inline', chart_path, 'npi_overview_pie')] + attachments

        sender.send_email(
            to_email=', '.join(recipients),
            subject="Weekly NPI Overview Report",
            body=html_body,
            is_html=True,
            attachments=attachments
        )

        logger.info(f"Email NPI settimanale inviata con successo a {len(recipients)} destinatari")
        logger.info(f"Allegato: {os.path.basename(attachment_path)}")
    except Exception as e:
        logger.error(f"Errore nell'invio dell'email NPI settimanale: {str(e)}")
        raise


def get_employee_work_email(conn, employee_name: str) -> Optional[str]:
    """
    Recupera l'indirizzo email lavorativo (WorkEmail) di un dipendente in base al nome completo.

    Args:
        conn: Connessione al database
        employee_name: Nome completo del dipendente (es. "TESTA GIANLUCA")

    Returns:
        L'indirizzo email lavorativo come stringa se trovato, altrimenti None
    """
    try:
        # Dividi il nome in cognome e nome
        # Assumendo formato "COGNOME NOME"
        parts = employee_name.strip().split()
        if len(parts) < 2:
            logger.warning(f"Formato nome non valido: {employee_name}")
            return None
        
        surname = parts[0]
        name = ' '.join(parts[1:])  # In caso di nomi composti
        
        query = """
        SELECT a.WorkEmail 
        FROM employee.dbo.employees e 
        INNER JOIN employee.dbo.EmployeeAddress a 
            ON a.EmployeeId = e.EmployeeId 
            AND a.DateOut IS NULL 
        INNER JOIN employee.dbo.employeehirehistory h 
            ON e.employeeid = h.employeeid 
            AND h.EndWorkDate IS NULL 
            AND h.employeerid = 2
        WHERE e.EmployeeSurname = ? AND e.EmployeeName = ?
        """

        with conn.cursor() as cursor:
            cursor.execute(query, (surname, name))
            row = cursor.fetchone()

        if row and row[0]:
            work_email = row[0].strip()
            logger.info(f"WorkEmail trovata per {employee_name}: {work_email}")
            return work_email

        logger.warning(f"Nessun risultato trovato per: {employee_name}")
        return None

    except Exception as e:
        logger.error(f"Errore nel recupero della WorkEmail per {employee_name}: {e}")
        raise


def send_fai_fails_notification(conn, logo_path: str = "logo.png") -> bool:
    """
    Invia email automatica per FAI fails non analizzati.
    
    Args:
        conn: Connessione al database
        logo_path: Percorso del logo aziendale
        
    Returns:
        True se email inviata con successo, False altrimenti
    """
    try:
        # 1. Recupera i fails non analizzati (DISTINCT per LabelCode)
        query_fails = """
        SELECT DISTINCT
            l.Operator,
            p.productcode,
            l.LabelCode
        FROM [Traceability_RS].[fai].[FaiLogs] l
        LEFT JOIN [Traceability_RS].[dbo].[orders] o ON l.OrderId = o.IDOrder
        LEFT JOIN [Traceability_RS].[dbo].[Products] p ON o.IDProduct = p.IDProduct
        WHERE l.IsOk = 0
            AND ISNULL(l.IsAnalized, 0) = 0
            AND l.DateOut IS NULL
        ORDER BY l.LabelCode
        """

        with conn.cursor() as cursor:
            cursor.execute(query_fails)
            fails = cursor.fetchall()

        if not fails:
            logger.info("Nessun FAI fail non analizzato trovato. Email non inviata.")
            return False

        # Raccoglie i LabelCode unici per il successivo UPDATE
        fail_labels = list(set(row.LabelCode for row in fails if row.LabelCode))
        num_fails = len(fail_labels)

        logger.info(f"Trovati {num_fails} FAI fails non analizzati ({len(fail_labels)} LabelCode unici)")
        
        # 2. Calcola statistiche per operatore (UNION ALL)
        query_stats = """
        SELECT
            UPPER(Operator) AS Operator,
            SUM(FailFAI)        AS FailFai,
            SUM(TotalCheckFai)  AS TotalCheckFai,
            SUM(TotalFails)     AS TotalFails,
            CAST(SUM(TotalFails) AS FLOAT) / NULLIF(SUM(TotalCheckFai), 0) * 100 AS ProcentFail
        FROM (
            -- Parte A: conta schede FAIL non analizzate per operatore
            SELECT
                l.Operator,
                COUNT(DISTINCT ISNULL(l.LabelCode, '0')) AS FailFAI,
                0 AS TotalCheckFai,
                0 AS TotalFails
            FROM [Traceability_RS].[fai].[FaiLogs] AS l
            WHERE l.IsOk = 0
                AND ISNULL(l.IsAnalized, 0) = 0
                AND l.DateOut IS NULL
            GROUP BY l.Operator

            UNION ALL

            -- Parte B: conta TUTTE le verifiche FAI attive per operatore
            SELECT
                Operator,
                0 AS FailFai,
                COUNT(DISTINCT LabelCode) AS TotalCheckFai,
                0 AS TotalFails
            FROM [Traceability_RS].[fai].[FaiLogs]
            WHERE DateOut IS NULL
            GROUP BY Operator

            UNION ALL

            -- Parte C: conta schede con almeno un FAIL attivo per operatore
            SELECT
                Operator,
                0 AS FailFAI,
                0 AS TotalCheckFai,
                COUNT(DISTINCT LabelCode) AS TotalFails
            FROM [Traceability_RS].[fai].[FaiLogs]
            WHERE IsOk = 0
                AND DateOut IS NULL
            GROUP BY Operator
        ) AS W
        GROUP BY UPPER(Operator)
        ORDER BY ProcentFail DESC
        """
        
        with conn.cursor() as cursor:
            cursor.execute(query_stats)
            statistics = cursor.fetchall()
        
        # 3. Recupera destinatari TO (capi linea/turno)
        query_recipients_to = """
        SELECT a.WorkEmail, 
               UPPER(e.EmployeeSurname + ' ' + e.EmployeeName) As Employee
        FROM employee.dbo.employees e
        INNER JOIN employee.dbo.EmployeeHireHistory h 
            ON h.employeeid = e.employeeid 
            AND h.EndWorkDate IS NULL 
            AND h.employeerid = 2
        INNER JOIN employee.dbo.EmployeeAddress a 
            ON a.EmployeeId = e.EmployeeId 
            AND a.dateout IS NULL
        INNER JOIN employee.dbo.EmployeeCdcStories ch 
            ON ch.EmployeeHireHistoryId = h.EmployeeHireHistoryId 
            AND ch.DateOut IS NULL
        INNER JOIN employee.dbo.CdcSub cs 
            ON cs.SubCdcId = ch.SubCdcId
        INNER JOIN employee.dbo.CostCenters c 
            ON c.CdcId = cs.CdcId
        INNER JOIN employee.dbo.functions f 
            ON ch.FunctionId = f.FunctionId
        WHERE f.FunctionId IN (5, 6, 7)
            AND a.WorkEmail IS NOT NULL
        ORDER BY a.WorkEmail
        """
        
        with conn.cursor() as cursor:
            cursor.execute(query_recipients_to)
            recipients_to_rows = cursor.fetchall()
        
        recipients_to = [row.WorkEmail.strip() for row in recipients_to_rows if row.WorkEmail]
        
        if not recipients_to:
            logger.error("Nessun destinatario TO trovato. Email non inviata.")
            return False
        
        logger.info(f"Destinatari TO: {recipients_to}")
        
        # 4. Recupera destinatari CC
        recipients_cc = get_email_recipients(conn, attribute='Sys_email_fai_fails')
        logger.info(f"Destinatari CC: {recipients_cc}")
        
        # 5. Genera tabella HTML con statistiche
        table_rows = ""
        for stat in statistics:
            operator = stat.Operator or 'N/A'
            fail_fai = stat.FailFai or 0
            total_check = stat.TotalCheckFai or 0
            total_fails = stat.TotalFails or 0
            procent_fail = float(stat.ProcentFail or 0)

            # Colore riga in base al tasso di fallimento
            if procent_fail < 5.0:
                row_color = "#d4edda"  # Verde chiaro
            elif procent_fail < 15.0:
                row_color = "#fff3cd"  # Giallo chiaro
            else:
                row_color = "#f8d7da"  # Rosso chiaro

            table_rows += f"""
            <tr style="background-color: {row_color};">
                <td style="padding: 10px; border: 1px solid #ddd;">{operator}</td>
                <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{fail_fai}</td>
                <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{total_check}</td>
                <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{total_fails}</td>
                <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">{procent_fail:.2f}%</td>
            </tr>
            """
        
        # 6. Genera corpo email HTML in rumeno
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <div style="margin-bottom: 20px;">
                <img src="cid:company_logo" alt="Company Logo" width="120"/>
            </div>
            
            <h2 style="color: #366092;">Raport Automat - Defecte FAI Nevalidate</h2>
            
            <p>Bună ziua,</p>
            
            <p>În legătură cu declarațiile FAI obligatorii, după un control automat asupra calității 
            fișelor declarate Valide pentru confirmarea începerii producției, a rezultat că 
            <strong>{num_fails} fișe</strong> au fost marcate ca <strong>FAIL</strong> după 
            declarația de validare.</p>
            
            <h3 style="color: #366092;">Statistici pe Operator:</h3>
            
            <table style="border-collapse: collapse; width: 100%; margin: 20px 0;">
                <thead>
                    <tr style="background-color: #366092; color: white;">
                        <th style="padding: 10px; border: 1px solid #ddd;">Operator</th>
                        <th style="padding: 10px; border: 1px solid #ddd;">Fail FAI (nevalidate)</th>
                        <th style="padding: 10px; border: 1px solid #ddd;">Total Verifiche FAI</th>
                        <th style="padding: 10px; border: 1px solid #ddd;">Total Defecte</th>
                        <th style="padding: 10px; border: 1px solid #ddd;">Procent Defecte (%)</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows}
                </tbody>
            </table>
            
            <hr style="margin: 30px 0; border: none; border-top: 1px solid #ddd;"/>
            
            <p style="font-weight: bold; color: #d9534f;">Vă recomandăm să acordați atenție maximă 
            în faza de validare a liniilor.</p>
            
            <p>Acest control este fundamental pentru a evita reparații inutile și, în consecință, 
            risipa de resurse și, evident, de bani.</p>
            
            <p>Responsabilitatea revine șefilor de linie și, în consecință, șefilor de tură.</p>
            
            <p style="font-style: italic;">În fiecare lună va fi întocmit un raport rezumativ cu 
            defectele de acest tip care vor influența evaluarea celor responsabili.</p>
            
            <br/>
            <p>Mulțumim,<br/>
            <strong>Sistem de Trasabilitate</strong></p>
        </body>
        </html>
        """

        # 7. Invia email
        sender = EmailSender()
        sender.save_credentials("Accounting@Eutron.it", "9jHgFhSs7Vf+")

        # Prepara allegati con logo inline
        attachments = []
        if os.path.exists(logo_path):
            attachments.append(('inline', logo_path, 'company_logo'))

        sender.send_email(
            to_email=', '.join(recipients_to),
            subject="Raport Automat - Defecte FAI Nevalidate",
            body=html_body,
            is_html=True,
            attachments=attachments,
            cc_emails=recipients_cc
        )

        logger.info(f"Email FAI fails inviata con successo a {len(recipients_to)} destinatari")

        # 8. Aggiorna flag IsAnalized tramite LabelCode dopo invio successo
        if fail_labels:
            placeholders = ','.join(['?' for _ in fail_labels])
            update_query = f"""
            UPDATE [Traceability_RS].[fai].[FaiLogs]
            SET IsAnalized = 1
            WHERE IsOk = 0
                AND ISNULL(IsAnalized, 0) = 0
                AND LabelCode IN ({placeholders})
            """

            with conn.cursor() as cursor:
                cursor.execute(update_query, fail_labels)
                conn.commit()

            logger.info(f"Aggiornati record con IsAnalized = 1 per {len(fail_labels)} LabelCode")
        else:
            logger.warning("Nessun LabelCode valido trovato per aggiornare IsAnalized")

        return True

    except Exception as e:
        logger.error(f"Errore nell'invio email FAI fails: {str(e)}", exc_info=True)
        return False
