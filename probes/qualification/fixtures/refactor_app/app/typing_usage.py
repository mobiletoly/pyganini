from app._pyganini.urls import urls

users_path: str = urls.users.path
user_path: str = urls.users.by_user_id("42").path
