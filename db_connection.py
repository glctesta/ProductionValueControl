# db_connection.py
import pyodbc
import threading


class DatabaseConnection:
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self._local = threading.local()

    @property
    def connection(self):
        return getattr(self._local, 'connection', None)

    @connection.setter
    def connection(self, value):
        self._local.connection = value

    def connect(self):
        """Crea una connessione al database usando le credenziali crittografate"""
        conn = self.connection
        if conn is not None:
            try:
                # Se la connessione è aperta, la riutilizziamo
                if not conn.closed:
                    return conn
            except Exception:
                pass
            self.connection = None

        config = self.config_manager.load_config()

        # Lista dei possibili driver da provare
        drivers = [
            'ODBC Driver 18 for SQL Server',
            'ODBC Driver 17 for SQL Server',
            'SQL Server',
            'SQL Server Native Client 11.0'
        ]

        # Trova il primo driver disponibile
        driver = None
        available_drivers = pyodbc.drivers()
        for d in drivers:
            if d in available_drivers:
                driver = d
                break

        if driver is None:
            raise Exception("Nessun driver SQL Server trovato. Installa un driver ODBC per SQL Server.")

        conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={config['server']};"
            f"DATABASE={config['database']};"
            f"UID={config['username']};"
            f"PWD={config['password']};"
            "Trusted_Connection=no;"
            "TrustServerCertificate=yes;"
            "Encrypt=yes;"
            "Connection Timeout=30;"
            "Mars_Connection=yes;"  # Gestione connessioni multiple
        )

        try:
            conn = pyodbc.connect(conn_str)
            conn.autocommit = True  # Evita transazioni pendenti
            self.connection = conn
            print("Connessione stabilita con successo!")
            return conn
        except pyodbc.Error as e:
            print(f"Errore durante la connessione: {str(e)}")
            raise

    def disconnect(self):
        """Chiude la connessione al database"""
        try:
            conn = self.connection
            if conn:
                try:
                    if not conn.closed:
                        conn.close()
                except Exception:
                    pass
                self.connection = None
        except Exception as e:
            print(f"Errore durante la chiusura della connessione: {str(e)}")

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

