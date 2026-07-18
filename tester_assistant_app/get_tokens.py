import os
from google_auth_oauthlib.flow import InstalledAppFlow

# Права доступа к Google Диску
SCOPES = ['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/drive']

def main():
    client_secrets = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'client_secrets.json')
    token_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'token.json')
    
    if not os.path.exists(client_secrets):
        print(f"Ошибка: Файл {client_secrets} не найден! Убедитесь, что скачали его и переименовали верно.")
        return

    print("Запуск авторизации через браузер...")
    flow = InstalledAppFlow.from_client_secrets_file(client_secrets, SCOPES)
    
    # Запускаем локальный сервер для перехвата токена
    creds = flow.run_local_server(port=0)

    # Сохраняем токен в файл
    with open(token_path, 'w') as token_file:
        token_file.write(creds.to_json())
        
    print("\nУСПЕШНО!")
    print(f"Токен сохранен в файл: {token_path}")
    print("Теперь ваш бэкенд сможет загружать файлы от вашего имени.")

if __name__ == '__main__':
    main()
