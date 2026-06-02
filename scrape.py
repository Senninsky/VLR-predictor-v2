# Importations
from vlrScraper import VlrScraper
from dbManager import DbManager

# Object creation
scraper = VlrScraper()
dbManager = DbManager()

# Print database info
print("Amount of total matches in database: " + str(dbManager.get_match_amount()))
print("Amount of total matches that have at least 1 odd available: " + str(dbManager.get_match_with_odds_amount()))

# Scrape matches
match_links = scraper.scrape_last_match_links(100)
amount = len(match_links)
last_matches = []
for i, match_link in enumerate(match_links):
    match = scraper.convert_match_link_to_match_object(match_link)
    dbManager.insert_match(match)

    print(str(i+1) + "/" + str(amount) + ": " + str(match) + "\n")
    last_matches.append(match)

dbManager.rescrape_missing_player_stats()