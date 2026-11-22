import ast,copy,json,pathlib,sys,traceback
import cv2,numpy as np
import tensorflow as tf
from tensorflow import keras
src,weights,truth_free_boxes,image_name,outpath=sys.argv[1:6]
src=pathlib.Path(src);weights=pathlib.Path(weights);out=pathlib.Path(outpath)
file=src/'edocr2/keras_ocr/recognition.py'
if not file.is_file():raise SystemExit('recognition.py not installed at '+str(file))
tree=ast.parse(file.read_text())
selected=[]
for node in tree.body:
    if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DEFAULT_BUILD_PARAMS' for t in node.targets):selected.append(node)
    if isinstance(node,ast.FunctionDef) and node.name in ('_repeat','_meshgrid','_transform'):selected.append(node)
    if isinstance(node,ast.FunctionDef) and node.name=='build_model':
        clone=copy.deepcopy(node)
        for idx,statement in enumerate(clone.body):
            if isinstance(statement,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='model' for t in statement.targets):
                clone.body=clone.body[:idx+1]+[ast.Return(value=ast.Name(id='model',ctx=ast.Load()))];break
        else:raise RuntimeError('Upstream build_model structure changed, no safe inference model')
        selected.append(clone)
ns={'tf':tf,'keras':keras,'np':np,'cv2':cv2}
exec(compile(ast.fix_missing_locations(ast.Module(body=selected,type_ignores=[])),'<upstream-inference-only>','exec'),ns)
texts=json.loads(pathlib.Path(truth_free_boxes).read_text())['readings']
image=cv2.imread(str(image_name))
if image is None:raise RuntimeError('image not readable')
outputs=[]
for weight in (weights/'recognizer_dimensions_2.keras',weights/'recognizer_gdts.keras'):
    if not weight.is_file() or not weight.with_suffix('.txt').is_file():continue
    alphabet=weight.with_suffix('.txt').read_text().rstrip('\n\r')
    model=ns['build_model'](alphabet=alphabet,**ns['DEFAULT_BUILD_PARAMS'])
    model.load_weights(str(weight))
    count=0
    for item in texts:
        b=item.get('bbox_px')
        if not isinstance(b,(list,tuple)) or len(b)!=4:continue
        x0,y0,x1,y1=map(int,b)
        x0=max(0,x0-2);y0=max(0,y0-2);x1=min(image.shape[1],x1+2);y1=min(image.shape[0],y1+2)
        if x1<=x0 or y1<=y0:continue
        gray=cv2.cvtColor(image[y0:y1,x0:x1],cv2.COLOR_BGR2GRAY)
        ratio=min(200/gray.shape[1],31/gray.shape[0]);ww=max(1,int(round(gray.shape[1]*ratio)));hh=max(1,int(round(gray.shape[0]*ratio)))
        patch=cv2.resize(gray,(ww,hh),interpolation=cv2.INTER_CUBIC)
        canvas=np.zeros((31,200),dtype=np.uint8);canvas[:min(31,hh),:min(200,ww)]=patch[:31,:200]
        probs=model(canvas[None,:,:,None].astype('float32')/255.0,training=False).numpy()
        seq=tf.fill([1],tf.shape(probs)[1]);decoded,_=tf.nn.ctc_greedy_decoder(tf.transpose(probs,[1,0,2]),seq)
        ids=decoded[0].values.numpy().tolist()
        word=''.join(alphabet[i] for i in ids if 0<=i<len(alphabet))
        outputs.append({'text':word,'bbox_px':[x0,y0,x1,y1], 'source_bbox':b,
             'recognizer':weight.name,'detection_source':'existing Paddle baseline boxes'})
        count+=1
    print('MODEL',weight.name,'CROPS',count,flush=True)
    keras.backend.clear_session()
out.write_text(json.dumps({'engine':'eDOCr2 specialized recognizers on Paddle-detected crops','readings':outputs},indent=2,ensure_ascii=False)+'\n')
