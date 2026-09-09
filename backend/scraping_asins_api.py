import requests

api_key = "6a8617226adeae490824d298"
url = "https://api.scrapingdog.com/amazon/product"

params = {
    "api_key": api_key,
    "asin": "B08RS4FQ1T",
    "country": "us",
    "domain": "com"
}

response = requests.get(url, params=params)

if response.status_code == 200:
    data = response.json()
    print(data)
else:
    print(f"Request failed with status code: {response.status_code}")