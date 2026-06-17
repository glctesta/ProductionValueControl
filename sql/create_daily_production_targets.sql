-- Tabella pianificazione target giornaliero di produzione.
-- Una riga per giorno lavorativo pianificato. I giorni senza riga
-- usano il fallback definito in config.json["dailyValue"].
IF NOT EXISTS (
    SELECT 1
    FROM sys.tables t
    INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
    WHERE s.name = 'dbo' AND t.name = 'DailyProductionTargets'
)
BEGIN
    CREATE TABLE traceability_rs.dbo.DailyProductionTargets (
        PlanDate    DATE          NOT NULL,
        DailyValue  DECIMAL(12,2) NOT NULL,
        Notes       NVARCHAR(255) NULL,
        CreatedAt   DATETIME2(0)  NOT NULL CONSTRAINT DF_DPT_CreatedAt DEFAULT SYSUTCDATETIME(),
        UpdatedAt   DATETIME2(0)  NULL,
        CONSTRAINT PK_DailyProductionTargets PRIMARY KEY (PlanDate),
        CONSTRAINT CK_DPT_DailyValue_Positive CHECK (DailyValue > 0)
    );

    PRINT 'Tabella DailyProductionTargets creata.';
END
ELSE
BEGIN
    PRINT 'Tabella DailyProductionTargets gia'' presente, nessuna azione.';
END
