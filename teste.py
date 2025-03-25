
def test_groq_key():
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    response = requests.get("https://api.groq.com/openai/v1/models", headers=headers)
    print("Status do teste de chave:", response.status_code)
    
test_groq_key() 