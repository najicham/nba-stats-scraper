# https://docs.python-requests.org/en/master/user/advanced/#timeouts
# https://findwork.dev/blog/advanced-usage-python-requests-timeouts-retries-hooks/
# https://www.scrapehero.com/how-to-rotate-proxies-and-ip-addresses-using-python-3/
# https://stackoverflow.com/questions/15431044/can-i-set-max-retries-for-requests-request


from pprint import pprint
from datetime import datetime, timedelta
from ..downloader_base import DownloaderBase
from ...utils.date_utils import validate_date_string
from ...utils.date_utils import convert_date_string
from ...utils.nba_utils import get_nba_season_from_date
from .bettingpros_nba_event_ids import BettingProsNBAEventIDs
from ...utils.project import is_local
from sports_ninja.exceptions import DownloadDataException

# 1. Books (below)
# 2. Seasons (below)
# 3. Events (called from set_opts)
# 4. Offer-Counts (ignored)
# 5. Offers (this)

# Markets (run in console)
# for (i in odds.markets.markets){
#     console.log(odds.markets.markets[i].id, odds.markets.markets[i].slug)
# }
markets = {
    156: 'points-by-player',
    157: 'rebounds-by-player',
    151: 'assists-by-player',
    162: 'threes-by-player',
    #147: 'most-points',
    160: 'steals-by-player',
    152: 'blocks-by-player',
    #142: 'first-basket',
    #136: 'double-double',
}

market_id_by_keyword = {
    'points': 156,
    'rebounds': 157,
    'assists': 151,
    'threes': 162,
    'steals': 160,
    'blocks': 152,
}

# https://api.bettingpros.com/v3/books
books = {
    0: "BettingPros Consensus",
    19: "BetMGM",
    27: "PartyCasino",
    10: "FanDuel",
    12: "DraftKings",
    20: "FOX Bet",
    14: "PointsBet",
    13: "Caesars",
    15: "SugarHouse",
    18: "BetRivers",
    28: "UniBet",
    21: "BetAmerica",
    29: "TwinSpires",
    22: "Oregon Lottery",
    24: "bet365",
    25: "WynnBET",
    26: "Tipico",
    30: "Betway",
    31: "Fubo",
}

# https://api.fantasypros.com/v3/seasons?sport=NBA&season=2021
# season_data = {
#     2021: {
#         "season_types": {
#             "REG":{
#                 "end": "2022-04-10 10:00:00",
#                 "periods": [],
#                 "start": "2021-10-19 16:30:00",
#                 "type": "REG",
#             }
#         },
#         "off_dates": [
#             "2021-11-25",
#             "2021-12-24",
#             "2022-02-18",
#             "2022-02-19",
#             "2022-02-20",
#             "2022-02-21",
#             "2022-02-22",
#             "2022-02-23",
#             "2022-04-04"
#         ]
#     }
# }


# $ ./ninja.py download bettingprosnbaplayerprops -a gamedate=2022-01-01 -a proptype=rebounds
# $ ./ninja.py download bettingprosnbaplayerprops -a gamedate=2022-06-07 -a proptype=rebounds
class GetBettingProsNBAPlayerProps(DownloaderBase):
    #these are all config options that do not get changed in the code
    #if they do get changed, it is with self.{attribute} = {new value}
    #and not mutating
    required_opts = ["gamedate", "proptype"]
    required_additional_opts = ["season", "event_ids", "events", "market_id"]
    use_proxy = True
    #proxy_log_file = "/tmp/proxy-stats4.txt"
    activity_log_file = "/tmp/bettingprosnbaplayerprops-activity.txt"
    activity_log_columns = ["gamedate", "time"]
    #stats_log_file = "/tmp/download-stats.txt"
    exporter_test = is_local() and True
    exporters = [
        {
            'type': 's3', 
            'key': "bettingpros/player-props/%(season)s/%(proptype)s/%(gamedate)s/%(time)s.json",
            'data_key': 'slice1',
            'groups': ["prod", "s3"],
        },
        {
            'type': 'file',# 'slack',
            'filename': '/tmp/bettingprosnbaplayerprops-%(gamedate)s-%(proptype)s',
            #'use_decoded_data': True,
            'data_key': 'slice1',
            'use_raw': True,
            'test': True,
            'groups': ["dev", "file"],
        }
    ]


    def slice_data(self):
        self.data["slice1"] = slice1_data(self.decoded_data, self.opts)
    
    
    def set_additional_opts(self):
        super().set_additional_opts()
        # check future dates if empty
        if "check_future_days" in self.opts:
            future_days = 7
        else:
            future_days = 0
        
        market_id = str(market_id_by_keyword[self.opts["proptype"]])
        
        if validate_date_string(self.opts["gamedate"]) == False:
            raise Exception("Invalid date string: "+self.opts["gamedate"])
        
        # this will change the opts gamedate
        events, gamedate = get_betting_pros_event_ids(self.opts["gamedate"], future_days)
        
        print("#############")
        pprint(events)
        
        if events == None:
            # if there are no NBA games on this date, check the events
            raise Exception("No BettingPros events found")
        else:
            event_ids = events.keys()

        self.opts["season"] = get_nba_season_from_date(self.opts["gamedate"])
        self.opts["event_ids"] = event_ids
        self.opts["events"] = events
        self.opts["market_id"] = market_id
        #"season_type": get_nbacom_url_season_type_from_date(gamedate)
    
    
    def validate_opts(self):
        super().validate_opts()
        
        if self.opts["proptype"] not in market_id_by_keyword:
            raise Exception("Invalid [proptype] valid values are: points, rebounds, assists, threes, steals, blocks")
        

    def set_url(self):
        # season = '2021'
        # date_from = self.opts["gamedate"]
        # date_to = date_from
        # season_type = self.opts["season_type"]  #"Regular+Season" #PlayIn, Playoffs
        converted_list = [str(element) for element in self.opts['event_ids']]
        event_ids = ":".join(converted_list)
        self.url = (
            "https://api.bettingpros.com/v3/offers?market_id="+self.opts['market_id']+"&event_id="+event_ids+"&location=ALL"
        )
        #"https://api.bettingpros.com/v3/offers?market_id=156&event_id=21477:21478:22097:21479:21480:21481&location=ALL"
        #'https://api.bettingpros.com/v3/events?sport=NBA&season='+season+'&date='+date_from


    def set_headers(self):
        self.headers = {
            #":authority": "api.bettingpros.com",
            #":method": "GET",
            #":path": "/v3/events?sport=NBA&season=2021&date=2022-01-11",
            #":scheme": "https",
            "accept": "application/json, text/plain, */*",
            "accept-encoding": "gzip, deflate, br",
            "accept-language": "en-US,en;q=0.9",
            "cache-control": "no-cache",
            "origin": "https://www.bettingpros.com",
            "pragma": "no-cache",
            "referer": "https://www.bettingpros.com/nba/odds/player-props/points-by-player/?date=2022-01-11",
            "sec-ch-ua": '"Chromium";v="97", " Not;A Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "Linux",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36",
            "x-api-key": "CHi8Hy5CEE4khd46XNYL23dCFX96oUdw6qOt1Dnh"
        }
    
    
    def validate_download_data(self):
        if "offers" not in self.decoded_data:
            raise DownloadDataException("[offers] not found in self.decoded_data")
        
        if not isinstance(self.decoded_data["offers"], list):
            raise DownloadDataException("[offers] is not a list")
        

    # def should_save_data(self):
    #     players_found = len(self.decoded_data["resultSets"][0]["rowSet"])
    #     if players_found > 0:
    #         should_save = True
    #     else:
    #         should_save = False
    #     # print(self.opts)
    #     print("Player name count: "+str(players_found)+", should save: "+str(should_save))
    #     return should_save


def slice1_data(data, opts):
    sliced = []
    for offer in data["offers"]:
        
        #pprint(offer)
        x = {}
        x["player_name"] = offer["participants"][0]['name']
        x["player_slug"] = offer["participants"][0]['player']['slug']
        x["proptype"] = opts["proptype"]
        x["gamedate"] = opts["gamedate"]
        #x["season"] = opts["season"]
        x["team"] = offer["participants"][0]['player']['team']
        x["position"] = offer["participants"][0]['player']['position']
        
        # not sure if opponent, home_game, and game_guid are essential
        # event = opts["events"][offer["event_id"]]
        # if x["team"] == event["home"]:
        #     x["opponent"] = event["away"]
        #     x["home_game"] = 1
        # else:
        #     x["opponent"] = event["home"]
        #     x["home_game"] = 0
        # x["game_guid"] = f"{event['away']}@{event['home']}"+x['gamedate'].replace("-", "")
        
        x["spreads"] = {}
        for selection in offer["selections"]:
            stype = selection["selection"]
            for book in selection["books"]:
                book_id = book["id"]
                line = book["lines"][0]
                if book_id not in x["spreads"]:
                    x["spreads"][book_id] = {
                        "book": books[book_id]
                    }
                x["spreads"][book_id][stype+"_line"] = line["line"]
                x["spreads"][book_id][stype+"_cost"] = line["cost"]
                x["spreads"][book_id][stype+"_update"] = line["updated"]
        sliced.append(x)
    #pprint(sliced)
    return sliced


def get_betting_pros_event_ids(gamedate, extra_days_to_check=0):
    bettingpros = BettingProsNBAEventIDs()
    max_extra_days = 6
    extra_days_to_check = min(extra_days_to_check, max_extra_days)
    orig_date = datetime.strptime(gamedate, "%Y-%m-%d")
    
    i = 0
    while i <= extra_days_to_check:
        date_to_check = orig_date + timedelta(days=i)
        gamedate = date_to_check.strftime("%Y-%m-%d")
        print("gamedate", gamedate)
        events = bettingpros.run({"gamedate": gamedate})
        #pprint(events)
        if events:
            return events, gamedate
        i += 1
    
    return None, gamedate
  
    
    