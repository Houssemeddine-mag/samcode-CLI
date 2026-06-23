import urllib.parse
import requests

def search_web(query: str, max_results: int = 5) -> str:
    """
    Searches the web using DuckDuckGo HTML and returns a formatted string of snippets.
    """
    try:
        from bs4 import BeautifulSoup
        
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
        })
        
        # Use the HTML version of DuckDuckGo to avoid JavaScript requirements
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        resp = session.get(url, timeout=10)
        
        if resp.status_code != 200: 
            return f"[SCRAPE_FAILED: Status {resp.status_code}]"
            
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Try to find snippets using the standard result class
        results = [
            a.get_text(strip=True) 
            for a in soup.find_all('a', class_='result__snippet', limit=max_results) 
            if a.get_text(strip=True)
        ]
        
        # Fallback if the class structure changed slightly
        if not results:
            for div in soup.find_all('div', class_='result__body', limit=max_results):
                snippet = div.find('a', class_='result__snippet')
                if snippet: 
                    results.append(snippet.get_text(strip=True))
                    
        # Add source verification
        verified_results = []
        for result in results:
            if result and len(result) > 20 and len(result) < 1000:
                verified_results.append(result)

        if verified_results:
            return "\n---\n".join([f"Result: {r}" for r in verified_results])
        else:
            return "[SCRAPE_FAILED: No valid text found. DuckDuckGo might have blocked the automated request.]"
            
    except Exception as e: 
        return f"[SCRAPE_FAILED: {str(e)}]"