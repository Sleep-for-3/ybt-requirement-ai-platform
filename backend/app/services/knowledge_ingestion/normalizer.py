import re,unicodedata
def normalize_content(text:str)->str:return re.sub(r"\s+"," ",unicodedata.normalize("NFKC",text or "")).strip().lower()
