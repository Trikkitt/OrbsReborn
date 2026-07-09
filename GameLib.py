import random

class gameClass:
    def __init__(self, GameLength, LaserStates, Orbs):
        self.QueuedActions=[]
        self.GameLength=GameLength
        self.GameStatus=0
        self.LaserStates=LaserStates
        self.Scores={0: [0,0], 1: [0,0], 2: [0,0]}
        self.Orbs=Orbs
    
    def GameStart(self):
        self.GameStartTime=time.time()
        self.GameStartTimeMS=time.ticks_ms()
        self.GameStatus=1
        
    def GameOver(self):
        self.GameStatus=2

    def ProcessOrbHit(self,OrbHit):
        Return False
        
    def GetOrbActions(self):
        NewOrbActions=self.QueuedActions
        self.QueuedActions=[]
        Return NewOrbActions
    
    def OrbFlashWhite(self,OrbID):
        colourmsg=bytearray(b'')
        colourmsg.append(4) # white
        colourmsg.append(2)
        colourmsg.append(2) # toggle interval 10 = 250ms
        colourmsg.append(40) # toggle count
        colourmsg.append(0)
        colourmsg.append(0)
        colourmsg.append(0)
        colourmsg.append(0)
        action=(OrbID,1,colourmsg)
        self.QueuedActions.append(action)

    def GetScores(self):
        Return self.Scores

    def ShotToGunID(self,ShotID):
        if ShotID==0x11:
            return 0
        elif ShotID==0x8A:
            return 1
        elif ShotID==0xB3:
            return 2
        else:
            return -1

class gameCoopBasic(gameClass):
    def GameStart(self):
        gameClass.GameStart()
        self.ActiveOrbs=["","",""]
        self.LastOrbs=["","",""]
        for gunID in range(0,2):
            if self.LaserState[gunID]==1:
                self.ActiveOrbs[gunID]=self.GetFreeOrb()
                self.SetOrbColour(self.ActiveOrbs[gunID],gunID)
    
    # byte 1 - 0 = off, 1 = on, 2 = flash
    # byte 2 - toggle interval
    # byte 3 - toggle count (0 = forever)
    # byte 4 - timer shift
    # byte 5 - bit 0 set = remain on
    def SetOrbColour(self,Orb,Colour):
        colourmsg=bytearray(b'')
        colourmsg.append(Colour)
        colourmsg.append(2) # flash
        colourmsg.append(4) # interval
        colourmsg.append(0) # flash forever
        colourmsg.append(0) # timer shift
        colourmsg.append(0) # options 0
        colourmsg.append(0) # options 0
        colourmsg.append(0) # options 0
        action=(Orb,1,colourmsg)
        self.QueuedActions.append(action)
        
    def SetOrbColourOff(self,Orb,Colour):
        colourmsg=bytearray(b'')
        colourmsg.append(Colour)
        colourmsg.append(0) # flash
        colourmsg.append(0) # interval
        colourmsg.append(0) # flash forever
        colourmsg.append(0) # timer shift
        colourmsg.append(0) # options 0
        colourmsg.append(0) # options 0
        colourmsg.append(0) # options 0
        action=(Orb,1,colourmsg)
        self.QueuedActions.append(action)
    
    def GetFreeOrb(self):
        ExcludedOrbs=self.ActiveOrbs + self.LastOrbs
        OrbIndex=random.randint(1,len(self.Orbs))
        OrbCount=0
        LastOrb=""
        for key in self.Orbs.keys():
            OrbCount+=1
            if OrbIndex==OrbCount:
                # This is our orb
                if key in ExcludedOrbs:
                    # this is excluded
                    if OrbCount==len(self.Orbs)
                        break
                    else:
                        OrbCount-=1
                else:
                    LastOrb=key
                    break
            elif not in ExcludedOrbs:
                LastOrb=key
        return LastOrb
    
    #def GetOrbActions(self):
    #    myActions=[]
    #    myActions.extend(gameClass.GetOrbActions())
    #    return myActions
    
    def ProcessOrbHit(self,OrbHit):
        gunID=gameClass.ShotToGunID(OrbHit[1])
        if gunID<0 or gunID>2: # We don't recognise this gun
            Return
        if self.LaserState[gunID]!=1: # Ignore if gun not in game
            Return
        gameClass.OrbFlashWhite(OrbHit[0])
        if OrbHit[0] in self.ActiveOrbs:
            # Player hit an active orb.
            self.Scores[gunID][0]+=1
            self.Scores[gunID][1]+=10
            NewOrb=self.GetFreeOrb()
            for r in range(0,2):
                if self.ActiveOrbs[r]==OrbHit[0]:
                    ActiveColour=r
            self.LastOrbs[r]=self.ActiveOrbs[r]
            self.ActiveOrbs[r]=NewOrb
            self.SetOrbColourOff(OrbHit[0],r)
            self.SetOrbColour(NewOrb,r)
        else:
            # Player hit the wrong orb.
            self.Scores[gunID][1]-=10
        
    
    
class gameCompBasic(gameClass):
    def GetOrbActions(self):
        myActions=gameClass.GetOrbActions()
        return myActions
    
    