# Настройка Miro для интерактивных досок

## Ошибка «Invalid redirect_uri»

Если при подключении Miro появляется сообщение вроде:

```
Invalid redirect_uri: 'https://boostudy.ru/auth/miro/callback' does not match any of the application registered values.
```

значит этот адрес не добавлен в настройках приложения Miro.

### Что сделать

1. Зайдите в [Miro Developer Platform](https://miro.com/app/settings/user-profile/apps) (или **Develop** → **Your apps** в Miro).
2. Откройте своё приложение (то, для которого указаны `MIRO_CLIENT_ID` и `MIRO_CLIENT_SECRET`).
3. В разделе **Redirect URI** (или **App redirect URLs**) добавьте **точно** такой адрес:
   - для продакшена: `https://boostudy.ru/auth/miro/callback`
   - для другого домена — тот URL, с которого пользователи заходят на сайт, плюс `/auth/miro/callback` (без завершающего слеша).
4. Сохраните настройки приложения в Miro.

После этого повторная попытка «Подключить Miro» должна проходить без ошибки redirect_uri.

### Переменная MIRO_REDIRECT_URI (по желанию)

Если нужно жёстко задать redirect URI (например, за прокси или при разных доменах), задайте в окружении:

```bash
MIRO_REDIRECT_URI=https://boostudy.ru/auth/miro/callback
```

Тогда приложение всегда будет использовать этот URL при OAuth, и он должен совпадать с тем, что указан в приложении Miro.
