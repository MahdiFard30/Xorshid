"""Small streaming pitch adjustment; mono PCM16, unchanged sample count/rate."""
import numpy as np

class PitchShifter:
    def __init__(self, semitones=0.0, rate=24000):
        if not -3 <= semitones <= 3: raise ValueError('Pitch must be between -3 and +3 semitones')
        self.semitones=float(semitones)
        self.ratio=2**(self.semitones/12)
        self.window=int(rate*.04)
        self.base=int(rate*.01)
        self.ring=np.zeros(16384,dtype=np.float32)
        self.reset()

    def reset(self):
        self.ring.fill(0)
        self.position=0
        self.phase=0.0

    def process(self, pcm):
        if not self.semitones: return pcm
        if len(pcm)%2: raise ValueError('PCM16 requires an even byte count')
        x=np.frombuffer(pcm,dtype='<i2').astype(np.float32)
        if not len(x):return pcm
        if len(x)>4096:raise ValueError('Audio block too large')
        size=len(self.ring);offset=np.arange(len(x));absolute=self.position+offset
        self.ring[absolute%size]=x
        step=(1-self.ratio)/self.window
        phase=(self.phase+offset*step)%1
        phase2=(phase+.5)%1
        def read(p):
            address=absolute-self.base-p*self.window
            lo=np.floor(address).astype(np.int64);frac=address-lo
            return self.ring[lo%size]*(1-frac)+self.ring[(lo+1)%size]*frac
        weight=.5-.5*np.cos(2*np.pi*phase)
        y=weight*read(phase)+(1-weight)*read(phase2)
        self.position+=len(x);self.phase=(self.phase+len(x)*step)%1
        return np.clip(np.rint(y),-32768,32767).astype('<i2').tobytes()
