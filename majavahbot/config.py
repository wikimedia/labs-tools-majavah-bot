from pywikibot import config
from os import path

effpr_config_page = 'User:MajavahBot/EFFP Helper Configuration'
requested_articles_config_page = 'Käyttäjä:MajavahBot/Asetukset/Artikkelitoiveiden siivoaja'

own_db_hostname = "localhost"
own_db_port = 3306
own_db_option_file = "local.my.cnf"
own_db_database = "majavahbot"

analytics_db_hostname = "localhost"
analytics_db_port = 4711
analytics_db_option_file = path.expanduser("~/replica.my.cnf")
