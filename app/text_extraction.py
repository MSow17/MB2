# app/text_extraction.py
import requests
import fitz  # PyMuPDF
import os
from app.logger import logger
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

PDF_DIR = os.getenv("PDF_DIR", "pdfs")
os.makedirs(PDF_DIR, exist_ok=True)


def download_pdf(url: str, article_id: int) -> str:
    """
    Télécharge un fichier PDF depuis une URL et le stocke localement.
    Si la réponse est HTML, tente :
      1) meta[name='citation_pdf_url']
      2) liens <a href>.pdf
      3) fallback DOI *.pdf
    Gestion SSLError avec verify=False
    """
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/pdf"}

    def attempt_download(target_url, verify_ssl=True):
        try:
            resp = requests.get(target_url, headers=headers, timeout=15, verify=verify_ssl)
            return resp
        except Exception as e:
            logger.warning(f"⚠️ Erreur requête {'sans SSL' if not verify_ssl else ''} pour article {article_id}: {e}")
            return None

    # 1ère tentative
    response = attempt_download(url)
    # en cas d'échec ou SSL error, retenter sans vérification
    if not response or response.status_code != 200:
        response = attempt_download(url, verify_ssl=False)
        if not response or response.status_code != 200:
            logger.warning(f"⚠️ HTTP {getattr(response, 'status_code', 'err')} pour article {article_id}")
            return None

    content_type = response.headers.get("Content-Type", "")
    if "application/pdf" in content_type:
        # PDF direct récupéré
        file_path = os.path.join(PDF_DIR, f"{article_id}.pdf")
        with open(file_path, 'wb') as f:
            f.write(response.content)
        logger.info(f"✅ PDF téléchargé : {file_path}")
        return file_path

    # Si HTML, on parse
    if "text/html" in content_type and response.text:
        logger.info(f"🔍 Page HTML reçue pour {article_id}, tentative de parsing PDF")
        soup = BeautifulSoup(response.text, 'html.parser')

        # 1) meta citation_pdf_url
        meta = soup.find('meta', attrs={'name': 'citation_pdf_url'})
        if meta and meta.get('content'):
            pdf_link = meta['content']
            logger.info(f"📋 meta citation_pdf_url trouvé : {pdf_link}")
            return download_pdf(pdf_link, article_id)

        # 2) liens .pdf
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.lower().endswith('.pdf'):
                pdf_link = urljoin(url, href)
                logger.info(f"🔗 Lien PDF trouvé dans HTML : {pdf_link}")
                return download_pdf(pdf_link, article_id)

        # 3) fallback DOI .pdf
        parsed = urlparse(url)
        if 'doi.org' in parsed.netloc and not parsed.path.lower().endswith('.pdf'):
            doi_pdf = url.rstrip('/') + '.pdf'
            logger.info(f"📄 Tentative DOI .pdf pour {article_id} : {doi_pdf}")
            return download_pdf(doi_pdf, article_id)

    logger.warning(f"⚠️ Contenu non PDF détecté pour {article_id} (type: {content_type})")
    return None



def extract_text_from_pdf(pdf_path: str) -> str:
    full_text = ""
    try:
        doc = fitz.open(pdf_path)
        for page in doc:
            texte = page.get_text()
            full_text += texte
    except Exception as e:
        logger.error(f"❌ Erreur extraction texte depuis {pdf_path} : {e}")
        return None
    finally:
        if 'doc' in locals():
            doc.close()

    if not full_text.strip():
        logger.warning(f"⚠️ Aucun texte extrait du PDF {pdf_path}")
        return None

    return full_text.strip()
