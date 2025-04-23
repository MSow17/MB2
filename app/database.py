import os
import time
import psycopg2
from psycopg2 import errors
from app.logger import logger
from app.nlp_grobid import detecter_controverse_via_tei


# === Configuration via .env ===
def get_env_or_exit(var):
    """
    Récupère une variable d'environnement ou lève une erreur si manquante.
    """
    value = os.getenv(var)
    if not value:
        logger.error(f"❌ Variable d'environnement manquante : {var}")
        raise RuntimeError(f"Variable d'environnement manquante : {var}")
    return value

POSTGRES_USER = get_env_or_exit("POSTGRES_USER")
POSTGRES_PASSWORD = get_env_or_exit("POSTGRES_PASSWORD")
POSTGRES_DB = get_env_or_exit("POSTGRES_DB")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")


class DatabaseManager:
    def __init__(self):
        try:
            self.conn = psycopg2.connect(
                dbname=POSTGRES_DB,
                user=POSTGRES_USER,
                password=POSTGRES_PASSWORD,
                host=POSTGRES_HOST,
                port=POSTGRES_PORT
            )
            self.conn.autocommit = True
            self.cur = self.conn.cursor()
            logger.info("📦 Connexion à PostgreSQL réussie")
        except Exception as e:
            self.conn = None
            self.cur = None
            logger.error(f"❌ Connexion à PostgreSQL échouée : {e}")
            raise

    def create_tables(self):
        if not self.conn:
            logger.error("⚠️ Impossible de créer les tables, la connexion à PostgreSQL a échoué.")
            return

        self._create_table_articles_oai()
        self._create_table_articles_openalex()
        self._create_table_grobid_metadata()
        self._create_table_meta()
        self.conn.commit()

    def _create_table_articles_oai(self):
        self.cur.execute("""
            CREATE TABLE IF NOT EXISTS articles_oai (
                id SERIAL PRIMARY KEY,
                titre TEXT NOT NULL,
                auteurs TEXT,
                date_publication DATE,
                resume TEXT,
                lien_pdf TEXT UNIQUE NOT NULL,
                texte_complet TEXT,
                est_controverse BOOLEAN DEFAULT NULL,
                score_controverse FLOAT DEFAULT NULL,
                extrait_controverse TEXT
            );
        """)
        logger.info("✅ Table 'articles_oai' prête.")

    def _create_table_articles_openalex(self):
        self.cur.execute("""
            CREATE TABLE IF NOT EXISTS articles_openalex (
                id SERIAL PRIMARY KEY,
                titre TEXT NOT NULL,
                auteurs TEXT,
                date_publication DATE,
                resume TEXT,
                lien_pdf TEXT UNIQUE NOT NULL,
                texte_complet TEXT,
                est_controverse BOOLEAN DEFAULT NULL,
                score_controverse FLOAT DEFAULT NULL,
                extrait_controverse TEXT
            );
        """)
        logger.info("✅ Table 'articles_openalex' prête.")

    def _create_table_grobid_metadata(self):
        self.cur.execute("""
            CREATE TABLE IF NOT EXISTS grobid_metadata (
                id SERIAL PRIMARY KEY,
                article_id INT NOT NULL,
                source TEXT NOT NULL,
                titre TEXT,
                resume TEXT,
                auteurs TEXT,
                citations TEXT,
                tei_xml TEXT,
                date_extraction TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                extrait_resume TEXT,
                est_controverse_tei BOOLEAN DEFAULT NULL,
                score_controverse_tei FLOAT DEFAULT NULL,
                extrait_controverse_tei TEXT,
                UNIQUE(article_id, source)
            );
        """)
        logger.info("✅ Table 'grobid_metadata' prête.")

    def _create_table_meta(self):
        self.cur.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        logger.info("✅ Table 'meta' prête.")

    def article_exists(self, table_name, lien_pdf):
        self.cur.execute(f"SELECT COUNT(*) FROM {table_name} WHERE lien_pdf = %s;", (lien_pdf,))
        return self.cur.fetchone()[0] > 0

    def insert_article(self, table_name, titre, auteurs, date_publication, resume, lien_pdf):
        try:
            self.cur.execute(f"""
                INSERT INTO {table_name} (titre, auteurs, date_publication, resume, lien_pdf)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id;
            """, (titre, auteurs, date_publication, resume, lien_pdf))
            article_id = self.cur.fetchone()[0]
            self.conn.commit()
            logger.info(f"✅ Article inséré dans '{table_name}' : {titre} (ID: {article_id})")
            return article_id
        except psycopg2.errors.UniqueViolation:
            self.conn.rollback()
            logger.warning(f"⚠️ Doublon détecté dans '{table_name}' pour lien : {lien_pdf}")
            return False

    def get_last_moisson_date(self):
        self.cur.execute("SELECT value FROM meta WHERE key = 'last_moisson_date';")
        row = self.cur.fetchone()
        return row[0] if row else None

    def set_last_moisson_date(self, date_str):
        self.cur.execute("""
            INSERT INTO meta (key, value) VALUES ('last_moisson_date', %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
        """, (date_str,))
        self.conn.commit()

    def save_text_to_db(self, article_id: int, text: str, table_name: str = "articles_openalex"):
        if table_name not in ("articles_openalex", "articles_oai"):
            logger.error(f"❌ Table non autorisée : {table_name}")
            return
        try:
            self.cur.execute(f"""
                UPDATE {table_name}
                SET texte_complet = %s
                WHERE id = %s;
            """, (text, article_id))
            self.conn.commit()
            logger.info(f"✅ Texte complet sauvegardé pour article {article_id} dans {table_name}")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"❌ Erreur sauvegarde texte complet : {e}")

    def save_controverse_to_db(self, table: str, article_id: int, est_controverse: bool, score: float, extrait: str = None):
        try:
            self.cur.execute(f"""
                UPDATE {table}
                SET est_controverse = %s,
                    score_controverse = %s,
                    extrait_controverse = %s
                WHERE id = %s;
            """, (est_controverse, score, extrait, article_id))
            self.conn.commit()
            logger.info(f"🧠 Controverse NLP enregistrée pour {table} ID={article_id}")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"❌ Erreur sauvegarde controverse : {e}")

    def save_grobid_metadata(self, article_id, source, titre, resume, auteurs, citations, tei_xml, extrait_resume=None):
        try:
            analyse = detecter_controverse_via_tei(tei_xml)
            self.cur.execute("""
                INSERT INTO grobid_metadata (
                    article_id, source, titre, resume, auteurs, citations, tei_xml,
                    extrait_resume, est_controverse_tei, score_controverse_tei, extrait_controverse_tei
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (article_id, source) DO UPDATE SET
                    titre = EXCLUDED.titre,
                    resume = EXCLUDED.resume,
                    auteurs = EXCLUDED.auteurs,
                    citations = EXCLUDED.citations,
                    tei_xml = EXCLUDED.tei_xml,
                    extrait_resume = EXCLUDED.extrait_resume,
                    est_controverse_tei = EXCLUDED.est_controverse_tei,
                    score_controverse_tei = EXCLUDED.score_controverse_tei,
                    extrait_controverse_tei = EXCLUDED.extrait_controverse_tei,
                    date_extraction = CURRENT_TIMESTAMP;
            """, (
                article_id, source, titre, resume, auteurs, str(citations), tei_xml,
                extrait_resume,
                analyse["est_controverse"],
                analyse["score"],
                analyse["extrait"]
            ))
            self.conn.commit()
            logger.info(f"📥 GROBID/TEI sauvegardé pour {source} ID={article_id}")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"❌ Erreur GROBID metadata : {e}")

    def get_article_by_id(self, table_name: str, article_id: int):
        if not self.conn or not self.cur:
            logger.error("❌ Connexion non initialisée.")
            return None

        if table_name not in ("articles_openalex", "articles_oai"):
            logger.error(f"❌ Table non autorisée : {table_name}")
            return None

        self.cur.execute(f"SELECT * FROM {table_name} WHERE id = %s;", (article_id,))
        return self.cur.fetchone()

    def close(self):
        if self.cur:
            self.cur.close()
        if self.conn:
            self.conn.close()
        logger.info("🔒 Connexion PostgreSQL fermée.")

    # Support pour "with"
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

