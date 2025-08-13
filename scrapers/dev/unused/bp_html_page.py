# https://docs.python-requests.org/en/master/user/advanced/#timeouts
# https://findwork.dev/blog/advanced-usage-python-requests-timeouts-retries-hooks/
# https://www.scrapehero.com/how-to-rotate-proxies-and-ip-addresses-using-python-3/
# https://stackoverflow.com/questions/15431044/can-i-set-max-retries-for-requests-request

import re
from ..downloader_base import DownloaderBase
from ...utils.date_utils import validate_date_string
from ...utils.date_utils import convert_date_string
from ...utils.nba_utils import get_nba_season_from_date
from ...utils.nba_utils import get_nbacom_url_season_type_from_date


class GetBettingProsHTMLPage(DownloaderBase):

    name = "getbettingproshtmlpage"
    #these are all config options that do not get changed in the code
    #if they do get changed, it is with self.{attribute} = {new value}
    #and not mutating
    use_proxy = False
    process_download_data = False
    download_type = "string"
    #proxy_log_file = "/tmp/proxy-stats4.txt"
    activity_log_file = "/tmp/getbettingproshtmlpage-activity.txt"
    activity_log_columns = ["gamedate", "time"]
    #stats_log_file = "/tmp/download-stats.txt"
    exporter_test = True
    exporters = [
        # {
        #     'type': 's3', 
        #     'key': "bettingpros/player-props/%(season)s/%(proptype)s/%(gamedate)s/%(time)s.json",
        #     'use_raw': True,
        # },
        {
            'type': 'file',
            'filename': '/tmp/getbettingproshtmlpage',
            'use_raw': True,
            #'data_key': 'file_data',
            'test': True
        }
    ]


    # def set_opts(self, opts):
    #     if "gamedate" not in opts:
    #         # maybe have a default setting for date
    #         raise Exception("[gamedate] is a required argument")

    #     gamedate = opts["gamedate"]
    #     is_valid = validate_date_string(gamedate)

    #     # check if date is a keyword and needs to be converted
    #     if is_valid == False:
    #         gamedate = convert_date_string(gamedate)
    #         if gamedate == False:
    #             raise Exception("Invalid date string: "+opts["gamedate"])

    #     self.opts = {
    #         "gamedate": gamedate,
    #         "season": get_nba_season_from_date(gamedate),
    #         "season_type": get_nbacom_url_season_type_from_date(gamedate)
    #     }


    def set_url(self):
        self.url = (
            'https://www.bettingpros.com/nba/odds/player-props/points-by-player/'
        )
    
    
    def process_download(self):
        domain = 'https://www.bettingpros.com'
        tag = ''
        content = self.download.content.decode("utf-8")
        for item in content.split("\n"):
            if "every-page" in item:
                tag = item.strip()
                break
        
        #<script type="text/javascript" src="/assets/js/min/bp-every-page-bdeab1363818f42b38b0.js"></script>
        x = re.search('src="(.*)"', tag)
        print(domain+x[1])
        exit()


    #def set_headers(self):
        # self.headers = {
        #     #":authority": "api.bettingpros.com",
        #     #":method": "GET",
        #     #":path": "/v3/events?sport=NBA&season=2021&date=2022-01-11",
        #     #":scheme": "https",
        #     "accept": "application/json, text/plain, */*",
        #     "accept-encoding": "gzip, deflate, br",
        #     "accept-language": "en-US,en;q=0.9",
        #     "cache-control": "no-cache",
        #     "origin": "https://www.bettingpros.com",
        #     "pragma": "no-cache",
        #     "referer": "https://www.bettingpros.com/nba/odds/player-props/points-by-player/?date=2022-01-11",
        #     "sec-ch-ua": '"Chromium";v="97", " Not;A Brand";v="99"',
        #     "sec-ch-ua-mobile": "?0",
        #     "sec-ch-ua-platform": "Linux",
        #     "sec-fetch-dest": "empty",
        #     "sec-fetch-mode": "cors",
        #     "sec-fetch-site": "same-site",
        #     "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36",
        #     "x-api-key": "CHi8Hy5CEE4khd46XNYL23dCFX96oUdw6qOt1Dnh"
        # }


    # def should_save_data(self):
    #     players_found = len(self.decoded_data["resultSets"][0]["rowSet"])
    #     if players_found > 0:
    #         should_save = True
    #     else:
    #         should_save = False
            
    #     # print(self.opts)
    #     print("Player name count: "+str(players_found)+", should save: "+str(should_save))
    #     return should_save