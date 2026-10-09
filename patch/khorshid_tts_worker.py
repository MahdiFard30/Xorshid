"""Private stdio worker: keep the original voice and models resident across replies."""
import contextlib
import copy
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
PROTOCOL = sys.stdout

def emit(**event):
    PROTOCOL.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + '\n')
    PROTOCOL.flush()


class Synthesizer:
    def __init__(self):
        import numpy as np
        import torch
        import soundfile as sf
        import sentencepiece as spm
        from huggingface_hub import hf_hub_download
        from transformers import AutoTokenizer, T5ForConditionalGeneration
        from pocket_tts import TTSModel
        from normalize_fa import normalize_for_model
        from tts_text import sentence_pieces, phoneme_pieces
        self.np, self.torch, self.sf = np, torch, sf
        self.normalize = normalize_for_model
        self.sentences, self.phoneme_chunks = sentence_pieces, phoneme_pieces
        self.voice_path = ROOT / 'my_voice_prompt.wav'
        voice, sr = sf.read(self.voice_path, dtype='float32', always_2d=True)
        if len(voice) < sr * .5 or np.max(np.abs(voice)) < .001:
            raise RuntimeError('Original my_voice_prompt.wav is missing, silent, or too short')
        self.voice_seconds = len(voice) / sr
        self.voice_stamp = self.voice_path.stat().st_mtime_ns
        requested = os.environ.get('KHORSHID_TTS_DEVICE', 'auto').lower()
        if requested not in ('auto','cpu','cuda'):
            raise ValueError('KHORSHID_TTS_DEVICE must be auto, cpu, or cuda')
        available = torch.cuda.is_available()
        if requested == 'cuda' and not available:
            raise RuntimeError('CUDA requested but not available in .tts-venv')
        self.device = 'cuda' if available and requested != 'cpu' else 'cpu'
        if self.device == 'cuda':
            # A real kernel catches incompatible builds, beyond is_available().
            x = torch.ones((16,16),device='cuda')
            (x @ x).sum().item()
            torch.cuda.synchronize()
        self.tokenizer = AutoTokenizer.from_pretrained('mehdi-hf/Homo-GE2PE-Persian-HF')
        self.g2p = T5ForConditionalGeneration.from_pretrained('mehdi-hf/Homo-GE2PE-Persian-HF').eval().to(self.device)
        self.sp = spm.SentencePieceProcessor(model_file=hf_hub_download('mehdi-hf/pocket-tts-farsi-v2','tokenizer_ph.model'))
        self.model = TTSModel.load_model(config='hf://mehdi-hf/pocket-tts-farsi-v2/model.yaml').to(self.device)
        # Full original file. No crop, resample, alternative voice or different model.
        self.state = self.model.get_state_for_audio_prompt(str(self.voice_path))
        self.rate = self.model.sample_rate
        self.mapping = str.maketrans({'/':'a','a':'A','@':'?','$':'S','c':'C'})

    def clone_state(self,value):
        torch=self.torch
        if isinstance(value,torch.Tensor):
            with torch.inference_mode(False), torch.no_grad():
                return value.detach().clone()
        if isinstance(value,dict):return {k:self.clone_state(v) for k,v in value.items()}
        if isinstance(value,list):return [self.clone_state(v) for v in value]
        if isinstance(value,tuple):return tuple(self.clone_state(v) for v in value)
        return copy.deepcopy(value)

    def count(self,s):
        return len(self.sp.encode(s,out_type=int))

    def synthesize(self,request):
        np,torch,sf=self.np,self.torch,self.sf
        started=time.monotonic()
        text=request['text']
        directory=Path(request['directory']).resolve()
        output=Path(request['output']).resolve()
        if not directory.is_dir():raise ValueError('Missing request directory')
        debug=ROOT/'.tts_debug';debug.mkdir(exist_ok=True)
        report={'text':text,'device':self.device,'chunks':[],'voice_used_seconds':self.voice_seconds,'status':'working'}
        def save():
            (debug/'latest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        all_pieces=[]
        try:
            # Honor a voice file edited between requests; otherwise reuse its state.
            stamp=self.voice_path.stat().st_mtime_ns
            if stamp!=self.voice_stamp:
                self.state=self.model.get_state_for_audio_prompt(str(self.voice_path))
                self.voice_stamp=stamp
            normalized=self.normalize(text)
            report['normalized_text']=normalized
            sentences=self.sentences(normalized)
            if not sentences:raise RuntimeError('No pronounceable text')
            # Work sentence by sentence: no waiting for the entire G2P paragraph.
            index=0
            for phrase_index,(phrase,pause) in enumerate(sentences):
                encoded=self.tokenizer([phrase.replace('؟','').replace('?','')],add_special_tokens=False,return_tensors='pt')
                encoded={k:v.to(self.device) for k,v in encoded.items()}
                with torch.no_grad():
                    ids=self.g2p.generate(**encoded,num_beams=5,max_length=512,early_stopping=True)
                if self.tokenizer.eos_token_id not in ids[0].tolist():
                    raise RuntimeError('G2P did not finish; refusing a truncated sentence')
                phonemes=self.tokenizer.batch_decode(ids,skip_special_tokens=True)[0].strip().translate(self.mapping)
                parts=self.phoneme_chunks(phonemes,self.count)
                if not parts:raise RuntimeError('Empty pronunciation')
                for part_index,part in enumerate(parts):
                    index+=1
                    cap=self.count(part)/3+2
                    attempts=[]
                    pcm=None
                    for attempt in range(3):
                        with torch.no_grad():
                            tensor=self.model.generate_audio(self.clone_state(self.state),part)
                        candidate=tensor.detach().cpu().numpy().reshape(-1).astype('float32')
                        duration=len(candidate)/self.rate
                        valid=bool(len(candidate) and np.isfinite(candidate).all() and duration<cap and np.max(np.abs(candidate))>.001)
                        attempts.append({'seconds':duration,'accepted':valid})
                        if valid:
                            pcm=candidate;break
                    report['chunks'].append({'source':phrase,'phonemes':part,'tokens':self.count(part),'attempts':attempts})
                    if pcm is None:raise RuntimeError(f'Voice chunk {index} failed duration/silence checks')
                    last=(phrase_index==len(sentences)-1 and part_index==len(parts)-1)
                    if not last:
                        silence=pause if part_index==len(parts)-1 else .10
                        pcm=np.concatenate((pcm,np.zeros(round(self.rate*silence),dtype='float32')))
                    path=directory/f'chunk-{index:04d}.wav'
                    sf.write(path,np.clip(pcm,-1,1),self.rate,subtype='PCM_16')
                    all_pieces.append(pcm)
                    if index==1:report['first_chunk_seconds']=time.monotonic()-started
                    save()
                    emit(type='chunk',id=request['id'],path=str(path))
            output.parent.mkdir(parents=True,exist_ok=True)
            temp=output.with_name(output.name+'.partial.wav')
            sf.write(temp,np.clip(np.concatenate(all_pieces),-1,1),self.rate,subtype='PCM_16')
            os.replace(temp,output)
            report['status']='ok';report['generation_seconds']=time.monotonic()-started
            save();emit(type='done',id=request['id'],path=str(output))
        except Exception as exc:
            report['status']='error';report['error']=str(exc);save();raise


def main():
    # Model libraries may print diagnostics: never mix them into JSON stdout.
    with contextlib.redirect_stdout(sys.stderr):
        try:
            synth=Synthesizer()
        except Exception as exc:
            emit(type='fatal',error=str(exc));return 1
        emit(type='ready',device=synth.device)
        for line in sys.stdin:
            request=None
            try:
                request=json.loads(line)
                if request.get('type')=='quit':return 0
                synth.synthesize(request)
            except Exception as exc:
                emit(type='error',id=(request or {}).get('id'),error=str(exc))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
