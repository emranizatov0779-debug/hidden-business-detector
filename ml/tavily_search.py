import json, urllib.request, urllib.error

TAVILY_URL = "https://api.tavily.com/search"

def get_tavily_key():
    import os
    key = os.environ.get('TAVILY_API_KEY','')
    if key: return key
    try:
        with open('data/tavily_config.json') as f:
            return json.load(f).get('api_key','')
    except Exception:
        return ''

def get_kazakhstan_aml_context(api_key):
    if not api_key: return ''
    queries = [
        "Kazakhstan AML fintech fraud scheme 2026",
        "Казахстан скрытый бизнес мошенничество схемы 2026",
    ]
    results = []
    for q in queries:
        try:
            payload = json.dumps({
                "api_key": api_key,
                "query": q,
                "search_depth": "basic",
                "max_results": 3,
            }).encode('utf-8')
            req = urllib.request.Request(
                TAVILY_URL, data=payload,
                headers={"Content-Type": "application/json"},
                method="POST")
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
                for item in data.get('results',[]):
                    results.append(f"- {item.get('title','')}: {item.get('content','')[:300]}")
        except Exception as e:
            results.append(f"Search error: {e}")
    if not results: return ''
    return "CURRENT NEWS FROM INTERNET:\n" + "\n".join(results[:6])
