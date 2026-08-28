from generated_urls import urls

urls.user()  # MISSING_PARAMETER
urls.user(extra=7)  # UNKNOWN_PARAMETER
urls.user("7")  # WRONG_PARAMETER_TYPE
