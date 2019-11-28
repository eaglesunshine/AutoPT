import time
import psutil
import requests
import Myconfig
import Mylogger
import globalvar as gl


class QBAPI(object):

    def __init__(self):
        self.logger = gl.get_value('logger').logger

        self._root = 'http://' + gl.get_value('config').qbaddr
        self.logger.info('QBAPI Init =' + self._root)

        self._session = requests.session()
        self._session.headers = {
            'User-Agent': 'Mozilla/5.0 AppleWebKit/537.36 Chrome/79.0.3945.16 Safari/537.36 Edg/79.0.309.11'
        }

        self.dynamiccapacity = gl.get_value('config').capacity

        self.maincategory = gl.get_value('config').maincategory
        self.subcategory = gl.get_value('config').subcategory
        self.checktrackerhttps = gl.get_value('config').checktrackerhttps
        self.diskletter = ''
        self.checkcategory()

    def checkcategory(self):
        if self.maincategory == '':
            self.logger.info('no maincategory')
            return
        info = self.get_url('/api/v2/torrents/categories')
        if info.status_code == 200:
            listjs = info.json()

            self.logger.info('maincategory:' + self.maincategory)
            if self.maincategory in listjs:
                self.diskletter = listjs[self.maincategory]['savePath'][0]
                self.logger.info('diskletter:' + self.diskletter)
            else:
                self.logger.error('category ' + self.maincategory + ' is not exist!!!!')
                exit(2)

            tempcategory = []
            self.logger.info('Befor filter subcategory:' + ','.join(self.subcategory))
            for val in self.subcategory:
                if val in listjs and listjs[val]['savePath'][0] == self.diskletter:
                    tempcategory.append(val)
            self.subcategory = tempcategory
            self.logger.info('After filter subcategory:' + ','.join(self.subcategory))
        else:
            self.logger.error('Error when get category list')

    def checksize(self, filesize):
        res = True
        if gl.get_value('config').autoflag and gl.get_value('config').capacity != 0:
            self.logger.info('QBAPI check filesize =' + str(filesize) + 'GB')

            gtl = self.gettorrentlist()
            totalsize = self.gettotalsize(gtl)

            diskremainsize = 1048576  # 设置无穷大的磁盘大小为1PB=1024*1024GB
            if self.diskletter != '':
                diskremainsize = self.getdisksize(self.diskletter)
                self.logger.info('diskremainsize =' + str(diskremainsize) + 'GB')
            self.dynamiccapacity = gl.get_value('config').capacity \
                if totalsize + diskremainsize > gl.get_value('config').capacity else totalsize + diskremainsize
            self.logger.info('dynamiccapacity =' + str(self.dynamiccapacity) + 'GB')

            if filesize > self.dynamiccapacity:
                self.logger.warning('Too big !!! filesize(' + str(filesize) + 'GB) > dynamic capacity(' +
                                    str(self.dynamiccapacity) + 'GB)')
                return False

            stlist, res = self.selecttorrent(filesize, gtl, totalsize)
            if not self.deletetorrent(stlist):
                self.logger.error('Error when delete torrent')
                return False
        return res

    def deletetorrent(self, stlist):
        ret = True
        for val in stlist:
            info = self.get_url('/api/v2/torrents/delete?hashes=' + val + '&deleteFiles=true')
            if info.status_code == 200:
                self.logger.info('delete torrent success , torrent hash =' + str(val))
                time.sleep(5)
            else:
                ret = False
                self.logger.error(
                    'delete torrent error ,status code = ' + str(info.status_code) + ', torrent hash =' + str(val))
        return ret

    def gettotalsize(self, gtl):
        sumsize = 0
        for val in gtl:
            sumsize += val['size']
        sumsize /= (1024 * 1024 * 1024)
        self.logger.info('torrent sum size =' + str(sumsize) + 'GB')
        return sumsize

    def selecttorrent(self, filesize, gtl, totalsize):
        deletesize = totalsize + filesize - self.dynamiccapacity
        self.logger.info('deletesize = ' + str(deletesize) + 'GB')
        d_list = []
        now = time.time()

        # need delete
        if deletesize > 0 and len(gtl) > 0:
            # 不删除 keeptorrenttime 小时内下载的种子
            infinte_lastactivity = [val for val in gtl
                                    if val['last_activity'] > now and
                                    now - val['added_on'] > gl.get_value('config').keeptorrenttime * 60 * 60]
            infinte_lastactivity.sort(key=lambda x: x['added_on'])
            # print (infinte_lastactivity)
            for val in infinte_lastactivity:
                d_list.append(val['hash'])
                deletesize -= val['size'] / 1024 / 1024 / 1024
                self.logger.info(
                    'select torrent name:\"' + val['name'] + '\"  size=' + str(val['size'] / 1024 / 1024 / 1024) + 'GB')
                if deletesize < 0:
                    break
            self.logger.info('torrent select part 1 , list len = ' + str(len(d_list)))
        if deletesize > 0 and len(gtl) > 0:
            # 不删除 keeptorrenttime 小时内下载的种子
            other_lastactivity = [val for val in gtl
                                  if val['last_activity'] <= now and
                                  now - val['added_on'] > gl.get_value('config').keeptorrenttime * 60 * 60]
            other_lastactivity.sort(key=lambda x: x['last_activity'])
            for val in other_lastactivity:
                d_list.append(val['hash'])
                deletesize -= val['size'] / 1024 / 1024 / 1024
                self.logger.info(
                    'select torrent name:\"' + val['name'] + '\"  size=' + str(val['size'] / 1024 / 1024 / 1024) + 'GB')
                if deletesize < 0:
                    break
            self.logger.info('torrent select part 2 , list len = ' + str(len(d_list)))
        if deletesize > 0:
            d_list = []
            return d_list, False
        else:
            return d_list, True

    def gettorrentlist(self):
        listjs = []
        if self.maincategory != '':
            info = self.get_url('/api/v2/torrents/info?category=' + self.maincategory)
            self.logger.debug('get list status code = ' + str(info.status_code))
            if info.status_code == 200:
                listjs = info.json()
            for val in self.subcategory:
                info = self.get_url('/api/v2/torrents/info?category=' + val)
                self.logger.debug('get ' + val + ' list status code = ' + str(info.status_code))
                if info.status_code == 200:
                    templistjs = info.json()
                    listjs += templistjs
        else:
            info = self.get_url('/api/v2/torrents/info?sort=last_activity')
            self.logger.debug('get list status code = ' + str(info.status_code))
            if info.status_code == 200:
                listjs = info.json()
        return listjs

    def istorrentexist(self, thash):
        info = self.get_url('/api/v2/torrents/info?hashes=' + thash)
        self.logger.debug('Is torrent exist status code = ' + str(info.status_code))
        if info.status_code == 200:
            listjs = info.json()
            return len(listjs) > 0
        return False

    def gettorrenttracker(self, thash):
        info = self.get_url('/api/v2/torrents/trackers?hash=' + thash)
        self.logger.debug('status code = ' + str(info.status_code))
        if info.status_code == 200:
            listjs = info.json()
            tracker = [val['url'] for val in listjs if val['status'] != 0]
            self.logger.debug('tracker:' + '\n'.join(tracker))
            return tracker
        elif info.status_code == 404:
            self.logger.error('Torrent hash was not found')
            return []

    def edittorrenttracker(self, thash, origin, new):
        info = self.get_url('/api/v2/torrents/editTracker?hash=' + thash +
                            '&origUrl=' + origin + '&newUrl=' + new)
        self.logger.debug('status code = ' + str(info.status_code))
        if info.status_code == 200:
            return True
        elif info.status_code == 400:
            self.logger.error('newUrl is not a valid URL')
        elif info.status_code == 404:
            self.logger.error('Torrent hash was not found')
        elif info.status_code == 409:
            self.logger.error('newUrl already exists for the torrent or origUrl was not found')
        return False

    def checktorrenttracker(self, thash):
        trackers = self.gettorrenttracker(thash)
        for val in trackers:
            if val.find('https') != 0 and val.find('http') == 0:
                new = val[:4] + 's' + val[4:]
                self.edittorrenttracker(thash, val, new)
                self.logger.error('更新tracker的http为https')

    def get_url(self, url):
        """Return BeautifulSoup Pages
        :url: page url
        :returns: BeautifulSoups
        """
        # self.logger.debug('Get url: ' + url)
        trytime = 3
        while trytime > 0:
            try:
                req = self._session.get(self._root + url)
                return req
            except BaseException as e:
                self.logger.error(e)
                trytime -= 1
                time.sleep(20)

    def post_url(self, url, data):
        """Return BeautifulSoup Pages
        :url: page url
        :returns: BeautifulSoups
        """
        # self.logger.debug('Get url: ' + url)
        trytime = 3
        while trytime > 0:
            try:
                req = self._session.post(self._root + url, files=data)
                return req
            except BaseException as e:
                self.logger.error(e)
                trytime -= 1
                time.sleep(20)

    def addtorrent(self, content, thash):
        data = {'torrents': content}
        if not self.istorrentexist(thash):
            info = self.post_url('/api/v2/torrents/add', data)
            self.logger.debug('addtorrent status code = ' + str(info.status_code))

            if info.status_code == 200:
                self.logger.info('addtorrent  successfully info hash = ' + thash)
                # info = self.get_url('/api/v2/torrents/info?sort=added_on&reverse=true')
                #
                # if info.status_code == 200:
                #     hash = info.json()[0]['hash']
                self.settorrentcategory(thash)
                if self.checktrackerhttps:
                    self.checktorrenttracker(thash)
                # else:
                #     self.logger.eroor('获取种子hash失败')
            else:
                self.logger.error('addtorrent Error status code = ' + str(info.status_code))
        else:
            self.logger.warning('torrent already exist hash=' + thash)

    def settorrentcategory(self, thash):
        if self.maincategory != '':
            info = self.get_url('/api/v2/torrents/setCategory?hashes=' + thash + '&category=' + self.maincategory)
            if info.status_code == 200:
                self.logger.info('set category successfully')
            else:
                self.logger.error('set category ERROR')

    def getdisksize(self, diskletter):
        p = psutil.disk_usage(diskletter + ':\\')[2] / 1024 / 1024 / 1024
        # self.logger.info(self.diskletter + '盘剩余空间' + str(p) + 'GB')
        return p


if __name__ == '__main__':
    gl._init()
    gl.set_value('config', Myconfig.Config())
    gl.set_value('logger', Mylogger.Mylogger())
    api = QBAPI()
    api.checktorrenttracker('bf004235c8c6dd62c33865a10937e97995f908c20')
