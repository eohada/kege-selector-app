import requests
from bs4 import BeautifulSoup

def main():
    session = requests.Session()
    
    # 1. Get Login Page to extract CSRF Token
    print("\n1. Fetching login page...")
    login_url = "http://127.0.0.1:5000/login"
    r = session.get(login_url)
    soup = BeautifulSoup(r.text, 'html.parser')
    csrf_input = soup.find('input', {'name': 'csrf_token'})
    csrf_token = csrf_input['value'] if csrf_input else None
    print(f"Found CSRF Token: {csrf_token}")
    
    # 2. Login
    print("\n2. Logging in...")
    payload = {
        'username': 'visual_audit_tutor',
        'password': 'VisualAudit123',
        'csrf_token': csrf_token
    }
    r = session.post(login_url, data=payload, allow_redirects=True)
    if 'Log In' in r.text or 'Войти' in r.text or r.status_code != 200:
        print("Login failed!")
        return
    print("Login successful!")

    # 3. Request /task-generator with lesson_id
    print(f"\n3. Fetching task-generator for lesson_id=1...")
    gen_url = f"http://127.0.0.1:5000/task-generator?lesson_id=1&assignment_type=homework&bank_open=1"
    r = session.get(gen_url)
    
    # Analyze the response
    soup = BeautifulSoup(r.text, 'html.parser')
    deck = soup.find(id='genDeck')
    print("--- GenDeck analysis ---")
    if deck:
        print("genDeck attributes:")
        for attr, val in deck.attrs.items():
            print(f"  {attr}: {val}")
    else:
        print("genDeck element not found!")

    # Find the bank panel
    bank_panel = soup.find(id='gen-bank-panel')
    print("--- GenBankPanel analysis ---")
    if bank_panel:
        print("gen-bank-panel attributes:")
        for attr, val in bank_panel.attrs.items():
            print(f"  {attr}: {val}")
    else:
        print("gen-bank-panel not found!")

    # Search for add to target buttons
    add_btns = soup.find_all(class_='bank-task-add-to-target-btn')
    print(f"Found {len(add_btns)} add-to-target buttons")
    if add_btns:
        print("First add button HTML:")
        print(add_btns[0])
    else:
        print("No add buttons found.")
            
if __name__ == '__main__':
    main()
