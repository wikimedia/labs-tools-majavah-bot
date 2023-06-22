from pathlib import Path

family = "wikipedia"
mylang = "en"

global usernames
usernames["vagrant"]["en"] = "MajavahBotti"
usernames["wikipedia"]["en"] = "MajavahBot"
usernames["wikipedia"]["fi"] = "MajavahBot"
usernames["wikipedia"]["sq"] = "MajavahBot"
usernames["wikiquote"]["sq"] = "MajavahBot"
usernames["wikidata"]["wikidata"] = "MajavahBot"
usernames["meta"]["meta"] = "MajavahBot"

if Path("/data/project/majavah-bot/.pywikibot/user-password.py").exists():
    password_file = "/data/project/majavah-bot/.pywikibot/user-password.py"
else:
    password_file = "user-password.py"
