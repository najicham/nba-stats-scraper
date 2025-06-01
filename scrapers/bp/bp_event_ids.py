# https://docs.python-requests.org/en/master/user/advanced/#timeouts
# https://findwork.dev/blog/advanced-usage-python-requests-timeouts-retries-hooks/
# https://www.scrapehero.com/how-to-rotate-proxies-and-ip-addresses-using-python-3/
# https://stackoverflow.com/questions/15431044/can-i-set-max-retries-for-requests-request


from ..downloader_base import DownloaderBase
from ...utils.date_utils import validate_date_string
from ...utils.date_utils import convert_date_string
from ...utils.nba_utils import get_nba_season_from_date
from ...utils.project import is_local


# $ ./ninja.py download bettingprosnbaeventids -a gamedate=2022-01-01
class BettingProsNBAEventIDs(DownloaderBase):
    #these are all config options that do not get changed in the code
    #if they do get changed, it is with self.{attribute} = {new value}
    #and not mutating
    use_proxy = True
    #proxy_log_file = "/tmp/proxy-stats4.txt"
    # activity_log_file = "/tmp/bettingprosnbaeventids-activity.txt"
    # activity_log_columns = ["gamedate", "time"]
    #stats_log_file = "/tmp/download-stats.txt"
    exporter_test = is_local() and True
    exporters = [
        {
            'active': False,
            'type': 's3', 
            'key': "bettingpros/event-ids/%(season)s/%(proptype)s/%(gamedate)s/%(time)s.json",
            'use_raw': True,
        },
        {
            'type': 'file', #'slack',
            'filename': '/tmp/bettingprosnbaeventids-%(gamedate)s',
            #'use_decoded_data': True,
            'data_key': 'events',
            'test': True
        }
    ]
    
    
    def slice_data(self):
        events = {}
        for event in self.decoded_data["events"]:
            events[event["id"]] = {
                "home": event["home"],
                "away": event["visitor"],
            }
        self.data["events"] = events
    
    
    def get_return_value(self):
        return self.data["events"]
    

    def set_opts(self, opts):
        if "gamedate" not in opts:
            # maybe have a default setting for date
            raise Exception("[gamedate] is a required argument")

        gamedate = opts["gamedate"]
        is_valid = validate_date_string(gamedate)

        # check if date is a keyword and needs to be converted
        if is_valid == False:
            gamedate = convert_date_string(gamedate)
            if gamedate == False:
                raise Exception("Invalid date string: "+opts["gamedate"])

        self.opts = {
            "gamedate": gamedate,
            "season": get_nba_season_from_date(gamedate),
            #"season_type": get_nbacom_url_season_type_from_date(gamedate)
        }


    def set_url(self):
        season = '2021'
        date_from = self.opts["gamedate"]
        #date_to = date_from
        #season_type = self.opts["season_type"]  #"Regular+Season" #PlayIn, Playoffs
        self.url = (
            'https://api.bettingpros.com/v3/events?sport=NBA&season='+season+'&date='+date_from
        )


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


    # def should_save_data(self):
    #     players_found = len(self.decoded_data["resultSets"][0]["rowSet"])
    #     if players_found > 0:
    #         should_save = True
    #     else:
    #         should_save = False
            
    #     # print(self.opts)
    #     print("Player name count: "+str(players_found)+", should save: "+str(should_save))
    #     return should_save