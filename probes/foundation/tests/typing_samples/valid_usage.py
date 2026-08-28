from generated_urls import urls

home_path: str = urls.home
user_path: str = urls.user(7).path
edit_path: str = urls.user(user_id=7).edit
