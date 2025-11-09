def GetVersionHigh():
    return 2

def GetVersionLow():
    return 2


def get_config():
    import json
    try:
        configfile=open("config.txt","r")
        cfgdict=json.load(configfile)
        configfile.close()
    except BaseException as e:
        cfgdict={}
    return cfgdict


def save_config(cfgdict):
    import json
    savesuccess=False
    try:
        cfgtxt=json.dumps(cfgdict)
        configfile=open("config.txt","w")
        configfile.write(cfgtxt)
        configfile.close()
        savesuccess=True
    except:
        savesuccess=False


def crc16(data):
    crc = 0xFFFF 
    for byte in data:
        crc = crc ^ byte
        for _ in range(8):
            if (crc & 0x01)==0:
                crc=crc >> 1
            else:
                crc=crc >> 1
                crc = crc ^ 0xA001
            crc &= 0xFFFF
    return crc

def connectwifi():
    import network
    import utime
    wifi_SSID='TheTardisGuest'
    wifi_PSK='Trikkitt'
    sta_if = network.WLAN(network.STA_IF)
    sta_if.active(True)
    sta_if.connect(wifi_SSID,wifi_PSK)
    loopcount=0
    while not sta_if.isconnected() and loopcount<10:
    	utime.sleep(2)
    	loopcount+=1
    if sta_if.isconnected()==False:
        sta.disconnect() 
        sta.config(channel=1)

    return sta_if.isconnected()



def downloadfile(filename):
    import os
    newfilename='new-' + filename
    try:
        os.remove(newfilename)
    except:
        a=1
    try:
        import requests
        url='https://raw.githubusercontent.com/Trikkitt/OrbsReborn/refs/heads/main/' + filename
        #r=requests.get(url)
        #open(filename,'wb').write(r.content)
        r=requests.get(url)
        data=r.text
        f=open(newfilename,'wb')
        f.write(data)
        f.close()
        r.close()
        filestat=os.stat(newfilename)
        if filestat[6]==14:
            return False
        else:
            return True
    except:
        return False


def DiscoverHost(pe,psta,puart):
    bcast = b'\xff' * 6
    mygamehost=b'\xff' * 6
    discoveryPacket=bytearray(b'\xfe\x05')
    discoveryPacket.extend(psta.config('mac'))
    crc=crc16(discoveryPacket)
    discoveryPacket.append(crc & 255)
    discoveryPacket.append(crc >> 8)

    while bcast==mygamehost:
        pe.send(bcast,discoveryPacket)
        host, msg=pe.irecv(2000)
        if not host:
            picmsg=bytearray(b'\xfe\x00\x00\x00\x00\x00\x00\x00')
            crc=crc16(picmsg)
            picmsg.append(crc & 255)
            picmsg.append(crc >> 8)
            puart.write(picmsg)
        else:
            if len(msg)==10:
                crc=crc16(msg)
                if crc==0 and msg[0]==0xfb and msg[1]==0x05:
                    mygamehost=msg[2:8]
    picmsg=bytearray(b'\xfb\x00\x00\x00\x00\x00\x00\x00')
    crc=crc16(picmsg)
    picmsg.append(crc & 255)
    picmsg.append(crc >> 8)
    puart.write(picmsg)
    return mygamehost

