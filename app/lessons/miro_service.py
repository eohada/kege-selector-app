"""
Сервис для работы с Miro API.
Создание досок, приглашение гостей, экспорт.
"""
import requests
from flask import current_app
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class MiroService:
    """Сервис для интеграции с Miro API v2."""
    
    BASE_URL = "https://api.miro.com/v2"
    
    def __init__(self, access_token: Optional[str] = None):
        """
        Инициализация сервиса.
        
        Args:
            access_token: Miro API токен. Если не указан, берётся из конфига.
        """
        self.access_token = access_token or current_app.config.get('MIRO_ACCESS_TOKEN')
        if not self.access_token:
            raise ValueError(
                "Нет токена Miro. Сначала авторизуйтесь в Miro по кнопке «Подключить Miro» на странице урока."
            )
        
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """
        Базовый метод для API запросов.
        
        Args:
            method: HTTP метод (GET, POST, PUT, DELETE)
            endpoint: Endpoint API (без базового URL)
            **kwargs: Дополнительные параметры для requests
        
        Returns:
            JSON ответ от API
        
        Raises:
            MiroAPIError: При ошибке API
        """
        url = f"{self.BASE_URL}{endpoint}"
        
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                timeout=30,
                **kwargs
            )
            
            # Логируем запрос
            logger.debug(f"Miro API {method} {endpoint}: {response.status_code}")
            
            # Проверяем статус
            if response.status_code >= 400:
                error_data = response.json() if response.text else {}
                logger.error(f"Miro API error: {response.status_code} - {error_data}")
                raise MiroAPIError(
                    status_code=response.status_code,
                    message=error_data.get('message', 'Unknown error'),
                    details=error_data
                )
            
            # Возвращаем JSON или пустой dict
            return response.json() if response.text else {}
            
        except requests.RequestException as e:
            logger.error(f"Miro API request failed: {e}")
            raise MiroAPIError(status_code=500, message=str(e))
    
    def create_board(
        self,
        name: str,
        description: str = "",
        team_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Создать новую доску.
        
        Args:
            name: Название доски
            description: Описание доски
            team_id: ID команды (опционально)
        
        Returns:
            Данные созданной доски
        """
        payload = {
            "name": name,
            "description": description,
            "policy": {
                "permissionsPolicy": {
                    "collaborationToolsStartAccess": "all_editors",
                    "copyAccess": "anyone",
                    "sharingAccess": "team_members_with_editing_rights"
                },
                "sharingPolicy": {
                    "access": "private",
                    "inviteToAccountAndBoardLinkAccess": "editor",
                    "organizationAccess": "private",
                    "teamAccess": "edit"
                }
            }
        }
        
        if team_id:
            payload["teamId"] = team_id
        
        return self._request("POST", "/boards", json=payload)
    
    def get_board(self, board_id: str) -> Dict[str, Any]:
        """
        Получить информацию о доске.
        
        Args:
            board_id: ID доски в Miro
        
        Returns:
            Данные доски
        """
        return self._request("GET", f"/boards/{board_id}")
    
    def delete_board(self, board_id: str) -> bool:
        """
        Удалить доску.
        
        Args:
            board_id: ID доски
        
        Returns:
            True если успешно
        """
        try:
            self._request("DELETE", f"/boards/{board_id}")
            return True
        except MiroAPIError:
            return False
    
    def share_board(
        self,
        board_id: str,
        email: str,
        role: str = "editor",
        message: str = ""
    ) -> Dict[str, Any]:
        """
        Пригласить пользователя на доску.
        
        Args:
            board_id: ID доски
            email: Email приглашаемого
            role: Роль (viewer, commenter, editor)
            message: Сообщение в приглашении
        
        Returns:
            Данные приглашения
        """
        payload = {
            "emails": [email],
            "role": role,
            "message": message
        }
        
        return self._request("POST", f"/boards/{board_id}/members", json=payload)
    
    def get_board_members(self, board_id: str) -> Dict[str, Any]:
        """
        Получить список участников доски.
        
        Args:
            board_id: ID доски
        
        Returns:
            Список участников
        """
        return self._request("GET", f"/boards/{board_id}/members")
    
    def create_share_link(self, board_id: str, access: str = "view") -> Dict[str, Any]:
        """
        Создать публичную ссылку на доску.
        
        Args:
            board_id: ID доски
            access: Тип доступа (view, comment, edit)
        
        Returns:
            Данные ссылки
        """
        payload = {
            "access": access
        }
        
        return self._request("POST", f"/boards/{board_id}/share-link", json=payload)
    
    def get_share_link(self, board_id: str) -> Optional[str]:
        """
        Получить публичную ссылку на доску.
        
        Args:
            board_id: ID доски
        
        Returns:
            URL ссылки или None
        """
        try:
            response = self._request("GET", f"/boards/{board_id}")
            return response.get("viewLink")
        except MiroAPIError:
            return None
    
    def export_board(
        self,
        board_id: str,
        format: str = "pdf"
    ) -> bytes:
        """
        Экспортировать доску в файл.
        
        ВНИМАНИЕ: Этот метод доступен только на Enterprise плане.
        Для Business плана используйте export_board_preview.
        
        Args:
            board_id: ID доски
            format: Формат (pdf, png)
        
        Returns:
            Содержимое файла в байтах
        """
        # Для Business плана экспорт напрямую недоступен
        # Возвращаем ссылку на доску для ручного экспорта
        raise MiroAPIError(
            status_code=403,
            message="Export API доступен только на Enterprise плане. Используйте встроенный экспорт Miro."
        )
    
    def get_team_info(self, team_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Получить информацию о команде.
        
        Args:
            team_id: ID команды (если не указан, вернёт все команды)
        
        Returns:
            Данные команды/команд
        """
        if team_id:
            return self._request("GET", f"/teams/{team_id}")
        
        # Получить все доступные команды
        return self._request("GET", "/teams")


class MiroAPIError(Exception):
    """Ошибка Miro API."""
    
    def __init__(
        self,
        status_code: int,
        message: str,
        details: Optional[Dict] = None
    ):
        self.status_code = status_code
        self.message = message
        self.details = details or {}
        super().__init__(f"Miro API Error {status_code}: {message}")


def get_miro_service(access_token: Optional[str] = None) -> MiroService:
    """
    Фабрика для создания MiroService.
    Использует переданный access_token (OAuth пользователя) или MIRO_ACCESS_TOKEN из конфига.
    Для создания досок и приглашений нужен токен пользователя после OAuth.
    
    Returns:
        Инстанс MiroService
    """
    return MiroService(access_token=access_token)
