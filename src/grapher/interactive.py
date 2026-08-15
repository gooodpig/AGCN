from __future__ import annotations

import html
import json
from pathlib import Path

from .parser import ParsedGgb, parse_ggb


def _point_coordinates(attrs: dict) -> list[float] | None:
    coords = attrs.get("coords", {})
    x_coord = coords.get("x")
    y_coord = coords.get("y")
    z_coord = coords.get("z", 1.0)
    if x_coord is None or y_coord is None or not z_coord:
        return None
    return [float(x_coord) / float(z_coord), float(y_coord) / float(z_coord)]


def _interactive_payload(parsed: ParsedGgb) -> dict:
    objects = []
    for obj in parsed.objects:
        attrs = obj.attrs
        item = {
            "name": obj.name,
            "kind": obj.kind,
            "visible": obj.visible,
            "labelVisible": obj.label_visible,
            "command": str(attrs.get("command", "")),
            "inputs": list(attrs.get("inputs", [])),
            "coords": _point_coordinates(attrs),
            "rawCoords": attrs.get("coords", {}),
            "matrix": attrs.get("matrix", {}),
            "color": list(attrs.get("color", (0, 0, 0))),
            "lineType": int(attrs.get("line_type", 0)),
            "lineThickness": float(attrs.get("line_thickness", 2.0)),
            "pointSize": float(attrs.get("point_size", 4.0)),
            "labelOffset": attrs.get("label_offset", {}),
            "value": attrs.get("value"),
            "outputIndex": int(attrs.get("command_output_index", 0)),
        }
        objects.append(item)

    viewport = parsed.viewport
    return {
        "objects": objects,
        "viewport": {
            "xMin": viewport.x_min,
            "xMax": viewport.x_max,
            "yMin": viewport.y_min,
            "yMax": viewport.y_max,
            "axesVisible": viewport.axes_visible,
            "gridVisible": viewport.grid_visible,
        },
    }


def _json_for_script(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def generate_interactive_html(
    input_path: str | Path,
    output_path: str | Path | None = None,
    *,
    width: int = 960,
    height: int = 640,
) -> str:
    """Create a self-contained interactive SVG preview for a GeoGebra file.

    Independent points created with the point tool are draggable. Supported
    dependent constructions are recomputed in the browser without GeoGebra.
    The static ``.asy`` output remains the source for publication-quality output.
    """
    source = Path(input_path)
    parsed = parse_ggb(source)
    payload = _json_for_script(_interactive_payload(parsed))
    title = f"{source.stem} — Asymptote interactive preview"
    page = _HTML_TEMPLATE.replace("__TITLE__", html.escape(title)).replace(
        "__FILE__", html.escape(source.name)
    ).replace("__WIDTH__", str(max(320, int(width)))).replace(
        "__HEIGHT__", str(max(240, int(height)))
    ).replace("__PAYLOAD__", payload)
    if output_path is not None:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(page, encoding="utf-8")
    return page


_HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>__TITLE__</title>
  <style>
    * { box-sizing: border-box; }
    html,body { margin:0; min-height:100%; background:#f4f5f7; color:#17191f; font:14px/1.45 system-ui,sans-serif; }
    header { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:12px 18px; background:#fff; border-bottom:1px solid #d8dadd; }
    h1 { margin:0; font-size:17px; overflow-wrap:anywhere; }
    button { border:1px solid #c8cbd0; border-radius:8px; padding:7px 12px; background:#fff; cursor:pointer; }
    button:hover { background:#f5f6f7; }
    main { display:grid; grid-template-columns:minmax(0,1fr) 250px; gap:14px; padding:14px; }
    #stage { width:100%; height:min(78vh,__HEIGHT__px); min-height:320px; display:block; background:#fff; border:1px solid #d4d7dc; border-radius:12px; box-shadow:0 2px 8px #0000000c; touch-action:none; }
    aside { border:1px solid #d4d7dc; border-radius:12px; padding:14px; background:#fff; box-shadow:0 2px 8px #0000000c; }
    aside h2 { margin:0 0 6px; font-size:15px; }
    aside p { margin:0 0 12px; color:#60646c; }
    #points { display:grid; gap:6px; margin:0; padding:0; list-style:none; }
    #points li { display:grid; grid-template-columns:minmax(40px,auto) 1fr; gap:8px; padding:6px 8px; border-radius:7px; background:#f6f7f9; }
    #points strong { color:#175cd3; overflow-wrap:anywhere; }
    #points span { color:#60646c; text-align:right; font-variant-numeric:tabular-nums; }
    .unsupported { margin-top:12px; color:#8a5b00; }
    @media (max-width:800px) { main { grid-template-columns:1fr; } aside { order:-1; } }
  </style>
</head>
<body>
  <header><h1>__FILE__ · Asymptote 交互预览</h1><button id="reset" type="button">恢复初始位置</button></header>
  <main>
    <svg id="stage" role="img" aria-label="可拖动的几何图形" preserveAspectRatio="xMidYMid meet"></svg>
    <aside>
      <h2>可拖动点</h2>
      <p>拖动独立描点或路径约束点；线、圆和常见依赖点会即时重算。黑色点与最终 Asymptote 风格一致。</p>
      <ul id="points"></ul>
      <div id="unsupported" class="unsupported"></div>
    </aside>
  </main>
  <script>
  (() => {
    'use strict';
    const model = __PAYLOAD__;
    const svg = document.querySelector('#stage');
    const list = document.querySelector('#points');
    const unsupportedNode = document.querySelector('#unsupported');
    const NS = 'http://www.w3.org/2000/svg';
    const byName = new Map(model.objects.map(object => [object.name, object]));
    const points = new Map();
    const initial = new Map();
    const movableNames = [];
    const pathParameters = new Map();
    const unsupported = new Set();
    let activePoint = null;

    for (const object of model.objects) {
      if (object.kind !== 'point' || !object.coords) continue;
      points.set(object.name, [...object.coords]);
      initial.set(object.name, [...object.coords]);
      if ((!object.command || ['point','pointin'].includes(object.command.toLowerCase())) && object.visible) movableNames.push(object.name);
    }

    const viewport = model.viewport;
    let xMin = Number(viewport.xMin), xMax = Number(viewport.xMax);
    let yMin = Number(viewport.yMin), yMax = Number(viewport.yMax);
    if (!(xMax > xMin && yMax > yMin)) [xMin,xMax,yMin,yMax] = [-10,10,-10,10];
    const spanX = xMax - xMin, spanY = yMax - yMin;
    svg.setAttribute('viewBox', `${xMin} ${-yMax} ${spanX} ${spanY}`);

    function node(tag, attrs={}) {
      const element = document.createElementNS(NS, tag);
      for (const [key,value] of Object.entries(attrs)) element.setAttribute(key, String(value));
      return element;
    }
    function point(name) {
      const direct=points.get(name); if (direct) return direct;
      let inline=/^Foot\[(.+),\s*(.+),\s*(.+)\]$/i.exec(name);
      if (inline) {
        const source=point(inline[1]), first=point(inline[2]), second=point(inline[3]);
        if (source&&first&&second) return projection(source,{point:first,direction:sub(second,first)});
      }
      inline=/^Midpoint\[(.+),\s*(.+)\]$/i.exec(name);
      if (inline) {
        const first=point(inline[1]), second=point(inline[2]);
        if (first&&second) return mul(add(first,second),.5);
      }
      return null;
    }
    function add(a,b) { return [a[0]+b[0],a[1]+b[1]]; }
    function sub(a,b) { return [a[0]-b[0],a[1]-b[1]]; }
    function mul(a,t) { return [a[0]*t,a[1]*t]; }
    function dot(a,b) { return a[0]*b[0]+a[1]*b[1]; }
    function cross(a,b) { return a[0]*b[1]-a[1]*b[0]; }
    function length(a) { return Math.hypot(a[0],a[1]); }
    function lineEndpoints(object) {
      const refs=object.inputs.map(point).filter(Boolean);
      const command=object.command.toLowerCase();
      if ((command==='polygon'||command==='polyline') && refs.length>=2 && object.outputIndex>0) {
        const edge=object.outputIndex-1, end=command==='polygon'?(edge+1)%refs.length:edge+1;
        if (end<refs.length) return [refs[edge],refs[end]];
      }
      if (refs.length>=2) return [refs[0],refs[1]];
      if (object.inputs.length===1) {
        const source=byName.get(object.inputs[0]);
        if (source) return lineEndpoints(source);
      }
      return null;
    }
    function vectorGeometry(name) {
      const object=byName.get(name); if (!object) return null;
      const endpoints=lineEndpoints(object); return endpoints?sub(endpoints[1],endpoints[0]):null;
    }
    function lineGeometry(name) {
      if (name === 'xAxis') return {point:[0,0],direction:[1,0]};
      if (name === 'yAxis') return {point:[0,0],direction:[0,1]};
      const inlineLine=/^Line\[(.+),\s*(.+)\]$/i.exec(name);
      if (inlineLine) {
        const first=point(inlineLine[1]), second=point(inlineLine[2]);
        if (first&&second) return {point:first,direction:sub(second,first)};
      }
      const object = byName.get(name); if (!object) return null;
      if (!['line','segment','ray','vector'].includes(object.kind)) return null;
      const [firstName,secondName] = object.inputs;
      const first = point(firstName), second = point(secondName);
      const command=object.command.toLowerCase();
      if ((command==='orthogonalline'||command==='parallelline') && first) {
        const base=lineGeometry(secondName); if (!base) return null;
        return {point:first,direction:command==='orthogonalline'?[-base.direction[1],base.direction[0]]:base.direction};
      }
      if (command==='linebisector' && first&&second) return {point:mul(add(first,second),.5),direction:[first[1]-second[1],second[0]-first[0]]};
      if ((command==='angularbisector'||command==='anglebisector') && first&&second&&point(object.inputs[2])) {
        const third=point(object.inputs[2]), firstVector=sub(first,second), thirdVector=sub(third,second);
        const firstLength=length(firstVector), thirdLength=length(thirdVector); if (firstLength<1e-12||thirdLength<1e-12) return null;
        return {point:second,direction:add(mul(firstVector,1/firstLength),mul(thirdVector,1/thirdLength))};
      }
      if ((command==='mirror'||command==='reflect') && object.inputs.length>=2) {
        const source=lineGeometry(object.inputs[0]); if (!source) return null;
        const center=point(object.inputs[1]);
        if (center) return {point:sub(mul(center,2),source.point),direction:mul(source.direction,-1)};
        const axis=lineGeometry(object.inputs[1]); if (!axis) return null;
        const first=sub(mul(projection(source.point,axis),2),source.point), sourceSecond=add(source.point,source.direction);
        const second=sub(mul(projection(sourceSecond,axis),2),sourceSecond);
        return {point:first,direction:sub(second,first)};
      }
      if (command==='tangent' && object.inputs.length>=2) {
        const tangentPoint=point(object.inputs[0])||point(object.inputs[1]);
        const circle=circleGeometry(point(object.inputs[0])?object.inputs[1]:object.inputs[0]);
        if (tangentPoint&&circle) {
          const centerVector=sub(tangentPoint,circle.center), distance=length(centerVector);
          if (distance>=circle.radius-1e-9 && distance>1e-12) {
            if (Math.abs(distance-circle.radius)<1e-8*Math.max(1,circle.radius)) return {point:tangentPoint,direction:[-centerVector[1],centerVector[0]]};
            const baseAngle=Math.atan2(centerVector[1],centerVector[0]);
            const offset=Math.acos(Math.min(1,circle.radius/distance));
            const candidates=[baseAngle+offset,baseAngle-offset].map(angle=>{
              const touch=add(circle.center,[circle.radius*Math.cos(angle),circle.radius*Math.sin(angle)]);
              return {point:tangentPoint,direction:sub(touch,tangentPoint)};
            });
            const raw=object.rawCoords||{}, initial=[-Number(raw.y||0),Number(raw.x||0)];
            if (length(initial)>1e-12) return candidates.reduce((best,item)=>Math.abs(cross(best.direction,initial))/Math.max(length(best.direction),1e-12)<Math.abs(cross(item.direction,initial))/Math.max(length(item.direction),1e-12)?best:item);
            return candidates[object.outputIndex%2];
          }
        }
      }
      const endpoints=lineEndpoints(object);
      if (endpoints) return {point:endpoints[0],direction:sub(endpoints[1],endpoints[0])};
      const raw=object.rawCoords||{}, x=Number(raw.x), y=Number(raw.y), z=Number(raw.z||0);
      if (Number.isFinite(x)&&Number.isFinite(y)&&Math.hypot(x,y)>1e-12) {
        const anchor=Math.abs(x)>Math.abs(y)?[-z/x,0]:[0,-z/y]; return {point:anchor,direction:[-y,x]};
      }
      return null;
    }
    function circleGeometry(name) {
      const inlineCircle=/^(?:Incircle|Circle)\[(.+),\s*(.+),\s*(.+)\]$/i.exec(name);
      if (inlineCircle) {
        const first=point(inlineCircle[1]), second=point(inlineCircle[2]), third=point(inlineCircle[3]);
        if (first&&second&&third) {
          if (/^Incircle/i.test(name)) {
            const center=triangleCenter(first,second,third,1), base={point:first,direction:sub(second,first)};
            return center?{center,radius:length(sub(center,projection(center,base)))}:null;
          }
          return circumcircle(first,second,third);
        }
      }
      const object = byName.get(name); if (!object || !['conic','conicpart'].includes(object.kind)) return null;
      const refs = object.inputs.map(point).filter(Boolean);
      const command=object.command.toLowerCase();
      if (command==='semicircle' && refs.length>=2) return {center:mul(add(refs[0],refs[1]),.5),radius:length(sub(refs[1],refs[0]))/2};
      if ((command==='circlearc'||command==='circlesector') && refs.length>=2) return {center:refs[0],radius:length(sub(refs[1],refs[0]))};
      if ((command==='circumcirclearc'||command==='circumcirclesector') && refs.length>=3) return circumcircle(refs[0],refs[1],refs[2]);
      if (command === 'circle') {
        if (refs.length === 2) return {center:refs[0],radius:length(sub(refs[1],refs[0]))};
        if (refs.length === 1 && object.inputs.length>=2) { const radius=numberValue(object.inputs[1]); if (radius!==null) return {center:refs[0],radius:Math.abs(radius)}; }
        if (refs.length >= 3) return circumcircle(refs[0],refs[1],refs[2]);
      }
      if (command==='incircle' && refs.length>=3) {
        const center=triangleCenter(refs[0],refs[1],refs[2],1), base={point:refs[0],direction:sub(refs[1],refs[0])};
        return center?{center,radius:length(sub(center,projection(center,base)))}:null;
      }
      if ((command==='mirror'||command==='reflect') && object.inputs.length>=2) {
        const source=circleGeometry(object.inputs[0]); if (!source) return null;
        const centerPoint=point(object.inputs[1]); if (centerPoint) return {center:sub(mul(centerPoint,2),source.center),radius:source.radius};
        const mirrorLine=lineGeometry(object.inputs[1]); if (mirrorLine) return {center:sub(mul(projection(source.center,mirrorLine),2),source.center),radius:source.radius};
      }
      const m = object.matrix || {}, a = Number(m.A0), b = Number(m.A1), c = Number(m.A2);
      const d = Number(m.A3 || 0), e = Number(m.A4 || 0), f = Number(m.A5 || 0);
      if (Number.isFinite(a) && Math.abs(a-b) < 1e-8 && Math.abs(d) < 1e-8 && Math.abs(a) > 1e-12) {
        const center = [-e/a,-f/a], radius2 = dot(center,center)-c/a;
        if (radius2 > 0) return {center,radius:Math.sqrt(radius2)};
      }
      return null;
    }
    function circumcircle(a,b,c) {
      const denominator = 2*cross(sub(b,a),sub(c,a)); if (Math.abs(denominator)<1e-10) return null;
      const aa=dot(a,a), bb=dot(b,b), cc=dot(c,c);
      const center=[(aa*(b[1]-c[1])+bb*(c[1]-a[1])+cc*(a[1]-b[1]))/denominator,
                    (aa*(c[0]-b[0])+bb*(a[0]-c[0])+cc*(b[0]-a[0]))/denominator];
      return {center,radius:length(sub(a,center))};
    }
    function lineLine(first,second) {
      const denominator=cross(first.direction,second.direction); if (Math.abs(denominator)<1e-10) return [];
      return [add(first.point,mul(first.direction,cross(sub(second.point,first.point),second.direction)/denominator))];
    }
    function lineCircle(line,circle) {
      const offset=sub(line.point,circle.center), a=dot(line.direction,line.direction);
      const b=2*dot(offset,line.direction), c=dot(offset,offset)-circle.radius*circle.radius;
      const discriminant=b*b-4*a*c; if (!(discriminant>=0) || a<1e-12) return [];
      const root=Math.sqrt(discriminant);
      return [add(line.point,mul(line.direction,(-b-root)/(2*a))),add(line.point,mul(line.direction,(-b+root)/(2*a)))];
    }
    function circleCircle(first,second) {
      const delta=sub(second.center,first.center), distance=length(delta);
      if (distance<1e-10 || distance>first.radius+second.radius+1e-9 || distance<Math.abs(first.radius-second.radius)-1e-9) return [];
      const along=(first.radius**2-second.radius**2+distance**2)/(2*distance);
      const height=Math.sqrt(Math.max(0,first.radius**2-along**2));
      const unit=mul(delta,1/distance), base=add(first.center,mul(unit,along)), normal=[-unit[1],unit[0]];
      return [add(base,mul(normal,height)),add(base,mul(normal,-height))];
    }
    function intersections(firstName,secondName) {
      const firstLine=lineGeometry(firstName), secondLine=lineGeometry(secondName);
      const firstCircle=circleGeometry(firstName), secondCircle=circleGeometry(secondName);
      if (firstLine&&secondLine) return lineLine(firstLine,secondLine);
      if (firstLine&&secondCircle) return lineCircle(firstLine,secondCircle);
      if (firstCircle&&secondLine) return lineCircle(secondLine,firstCircle);
      if (firstCircle&&secondCircle) return circleCircle(firstCircle,secondCircle);
      return [];
    }
    function numberValue(name) {
      const direct=Number(name); if (Number.isFinite(direct)) return direct;
      const object=byName.get(name), value=Number(object&&object.value); return Number.isFinite(value)?value:null;
    }
    function projection(position,line) {
      const scale=dot(sub(position,line.point),line.direction)/Math.max(dot(line.direction,line.direction),1e-20);
      return add(line.point,mul(line.direction,scale));
    }
    function pathParameter(object, position) {
      const sourceName=object.inputs[0], line=lineGeometry(sourceName), circle=circleGeometry(sourceName);
      if (line) return {kind:'line',value:dot(sub(position,line.point),line.direction)/Math.max(dot(line.direction,line.direction),1e-20)};
      if (circle) { const direction=sub(position,circle.center), magnitude=length(direction); return {kind:'circle',value:magnitude>1e-12?mul(direction,1/magnitude):[1,0]}; }
      return null;
    }
    function pointFromParameter(object, parameter) {
      const sourceName=object.inputs[0];
      if (parameter.kind==='line') { const line=lineGeometry(sourceName); return line?add(line.point,mul(line.direction,parameter.value)):null; }
      if (parameter.kind==='circle') { const circle=circleGeometry(sourceName); return circle?add(circle.center,mul(parameter.value,circle.radius)):null; }
      return null;
    }
    function constrainMovable(name, candidate) {
      const object=byName.get(name), command=object.command.toLowerCase();
      if (command==='point') {
        const parameter=pathParameter(object,candidate); if (!parameter) return point(name);
        pathParameters.set(name,parameter); return pointFromParameter(object,parameter);
      }
      return candidate;
    }
    function triangleCenter(first,second,third,index) {
      if (index===2) return mul(add(add(first,second),third),1/3);
      const circle=circumcircle(first,second,third);
      if (index===3) return circle&&circle.center;
      if (index===4) {
        const altitudeA={point:first,direction:[second[1]-third[1],third[0]-second[0]]};
        const altitudeB={point:second,direction:[first[1]-third[1],third[0]-first[0]]};
        return lineLine(altitudeA,altitudeB)[0]||null;
      }
      const a=length(sub(second,third)), b=length(sub(first,third)), c=length(sub(first,second)), total=a+b+c;
      return total>1e-12?mul(add(add(mul(first,a),mul(second,b)),mul(third,c)),1/total):null;
    }
    function recomputePoint(object) {
      const command=object.command.toLowerCase(), refs=object.inputs.map(point);
      if (command==='point') {
        let parameter=pathParameters.get(object.name);
        if (!parameter) { parameter=pathParameter(object,initial.get(object.name)); if (parameter) pathParameters.set(object.name,parameter); }
        return parameter&&pointFromParameter(object,parameter);
      }
      if (command==='pointin') return point(object.name);
      if (command==='midpoint' && refs[0]&&refs[1]) return mul(add(refs[0],refs[1]),.5);
      if (command==='midpoint' && object.inputs[0]) { const source=byName.get(object.inputs[0]), endpoints=source&&lineEndpoints(source); return endpoints?mul(add(endpoints[0],endpoints[1]),.5):null; }
      if ((command==='center'||command==='centre') && object.inputs[0]) { const circle=circleGeometry(object.inputs[0]); return circle&&circle.center; }
      if (command==='foot' && refs[0]&&refs[1]&&refs[2]) return projection(refs[0],{point:refs[1],direction:sub(refs[2],refs[1])});
      if (command==='foot' && refs[0]&&object.inputs[1]) { const line=lineGeometry(object.inputs[1]); return line?projection(refs[0],line):null; }
      if (['orthocenter','centroid','trianglecenter','circumcenter','incenter'].includes(command) && refs[0]&&refs[1]&&refs[2]) {
        const index=command==='orthocenter'?4:command==='centroid'?2:command==='circumcenter'?3:command==='incenter'?1:numberValue(object.inputs[3])||1;
        return triangleCenter(refs[0],refs[1],refs[2],index);
      }
      if (command==='translate' && refs[0]&&refs[1]&&refs[2]) return add(refs[0],sub(refs[2],refs[1]));
      if (command==='translate' && refs[0]&&object.inputs[1]) { const vector=vectorGeometry(object.inputs[1]); return vector?add(refs[0],vector):null; }
      if (command==='dilate' && refs[0]&&refs[2]) {
        const factor=numberValue(object.inputs[1]); if (factor!==null) return add(refs[2],mul(sub(refs[0],refs[2]),factor));
      }
      if ((command==='mirror'||command==='reflect') && refs[0]&&object.inputs[1]) {
        if (refs[1]) return sub(mul(refs[1],2),refs[0]);
        const line=lineGeometry(object.inputs[1]); if (line) return sub(mul(projection(refs[0],line),2),refs[0]);
      }
      if (command==='rotate' && refs[0]&&refs[2]) {
        const angle=numberValue(object.inputs[1]); if (angle===null) return null;
        const vector=sub(refs[0],refs[2]), cosine=Math.cos(angle), sine=Math.sin(angle);
        return add(refs[2],[vector[0]*cosine-vector[1]*sine,vector[0]*sine+vector[1]*cosine]);
      }
      if (command==='intersect' && object.inputs.length>=2) {
        const candidates=intersections(object.inputs[0],object.inputs[1]);
        const expected=initial.get(object.name); if (!candidates.length||!expected) return null;
        return candidates.reduce((best,item)=>length(sub(item,expected))<length(sub(best,expected))?item:best);
      }
      return null;
    }
    function recompute() {
      for (let pass=0; pass<model.objects.length; pass++) {
        let changed=false;
        for (const object of model.objects) {
          if (object.kind!=='point'||!object.command) continue;
          const value=recomputePoint(object); if (!value) continue;
          const old=point(object.name);
          if (!old||length(sub(old,value))>1e-10) { points.set(object.name,value); changed=true; }
        }
        if (!changed) break;
      }
    }
    function colorFor(object) {
      const [r,g,b]=object.color || [0,0,0];
      if (Math.max(r,g,b)-Math.min(r,g,b)<22) return '#111';
      return `rgb(${r},${g},${b})`;
    }
    function dashFor(type) { return type===0 ? '' : type===10 ? `${.012*spanX} ${.008*spanX}` : `${.02*spanX} ${.012*spanX}`; }
    function styleFor(object) {
      return {fill:'none',stroke:colorFor(object),'stroke-width':Math.max(.8,.3*object.lineThickness),'stroke-dasharray':dashFor(object.lineType),'vector-effect':'non-scaling-stroke'};
    }
    function screenLine(object) {
      const geometry=lineGeometry(object.name); if (!geometry) return null;
      const extent=4*Math.max(spanX,spanY)/Math.max(length(geometry.direction),1e-12);
      return [add(geometry.point,mul(geometry.direction,-extent)),add(geometry.point,mul(geometry.direction,extent))];
    }
    function pathFor(object) {
      const refs=object.inputs.map(point), command=object.command.toLowerCase();
      if (object.kind==='segment' && command==='polygon' && refs.filter(Boolean).length>=2) {
        const vertices=refs.filter(Boolean), index=Math.max(0,object.outputIndex-1)%vertices.length;
        return `M${vertices[index]} L${vertices[(index+1)%vertices.length]}`;
      }
      if (object.kind==='segment' && refs[0]&&refs[1]) return `M${refs[0]} L${refs[1]}`;
      if (object.kind==='line') { const ends=screenLine(object); return ends ? `M${ends[0]} L${ends[1]}` : null; }
      if ((object.kind==='ray'||object.kind==='vector') && refs[0]&&refs[1]) {
        if (object.kind==='ray') { const direction=sub(refs[1],refs[0]); return `M${refs[0]} L${add(refs[0],mul(direction,4*Math.max(spanX,spanY)/Math.max(length(direction),1e-12)))}`; }
        return `M${refs[0]} L${refs[1]}`;
      }
      if ((object.kind==='polyline'||object.kind==='polygon') && refs.length>=2) return `M${refs.join(' L')}${object.kind==='polygon'?' Z':''}`;
      if ((command==='semicircle'||command.includes('arc')) && refs.length>=2) {
        const center=command==='semicircle'?mul(add(refs[0],refs[1]),.5):refs[0];
        const start=command==='semicircle'?refs[0]:refs[1], end=command==='semicircle'?refs[1]:refs[2];
        if (!end) return null; const radius=length(sub(start,center));
        const initialPoint=initial.get(object.name); let sweep=0;
        if (initialPoint) sweep=cross(sub(start,center),sub(initialPoint,center))>=0?0:1;
        return `M${start} A${radius},${radius} 0 0,${sweep} ${end}`;
      }
      return null;
    }
    function labelDirection(object,position) {
      const offset=object.labelOffset||{};
      if (Number.isFinite(offset.x)||Number.isFinite(offset.y)) {
        const direction=[Number(offset.x||0),-Number(offset.y||0)], magnitude=length(direction);
        if (magnitude>1e-9) return mul(direction,1/magnitude);
      }
      const center=[(xMin+xMax)/2,(yMin+yMax)/2], direction=sub(position,center), magnitude=length(direction)||1;
      return mul(direction,1/magnitude);
    }
    function displayLabel(name) {
      return name.replace(/_([A-Za-z0-9]+)/g,'$1');
    }
    function appendLabelContent(label,name) {
      const match=/^(.*?)(?:_([A-Za-z0-9]+))?$/.exec(name);
      const base=node('tspan'); base.textContent=match?match[1]:name; label.append(base);
      if (match&&match[2]) {
        const subscript=node('tspan',{'baseline-shift':'sub','font-size':'70%'});
        subscript.textContent=match[2]; label.append(subscript);
      }
    }
    function boxesOverlap(first,second) {
      return Math.max(0,Math.min(first.right,second.right)-Math.max(first.left,second.left))*Math.max(0,Math.min(first.top,second.top)-Math.max(first.bottom,second.bottom));
    }
    function chooseLabelLayout(object,position,fontSize,pixel,placedLabels,pointPositions) {
      const preferred=labelDirection(object,position), diagonal=Math.SQRT1_2;
      const directions=[[1,0],[diagonal,diagonal],[0,1],[-diagonal,diagonal],[-1,0],[-diagonal,-diagonal],[0,-1],[diagonal,-diagonal]];
      directions.sort((first,second)=>dot(second,preferred)-dot(first,preferred));
      const text=displayLabel(object.name), width=Math.max(.55,Array.from(text).length*.58)*fontSize/pixel, height=1.05*fontSize/pixel;
      let best=null;
      for (let index=0;index<directions.length;index++) {
        const direction=directions[index], projected=Math.abs(direction[0])*width/2+Math.abs(direction[1])*height/2;
        const center=add(position,mul(direction,projected+9/pixel));
        const box={left:center[0]-width/2,right:center[0]+width/2,bottom:center[1]-height/2,top:center[1]+height/2};
        let score=index*3;
        for (const placed of placedLabels) score+=boxesOverlap(box,placed)*pixel*pixel*160;
        for (const other of pointPositions) {
          if (Math.abs(other[0]-position[0])<1e-10&&Math.abs(other[1]-position[1])<1e-10) continue;
          if (other[0]>=box.left&&other[0]<=box.right&&other[1]>=box.bottom&&other[1]<=box.top) score+=500;
        }
        if (box.left<xMin||box.right>xMax||box.bottom<yMin||box.top>yMax) score+=1000;
        if (!best||score<best.score) best={center,box,score,text};
      }
      return best;
    }
    function render() {
      recompute(); svg.replaceChildren(); unsupported.clear();
      const geometryLayer=node('g',{transform:'scale(1,-1)'}), labelLayer=node('g');
      svg.append(geometryLayer,labelLayer);
      if (viewport.axesVisible) {
        geometryLayer.append(node('line',{x1:xMin,y1:0,x2:xMax,y2:0,stroke:'#222','stroke-width':1,'vector-effect':'non-scaling-stroke'}));
        geometryLayer.append(node('line',{x1:0,y1:yMin,x2:0,y2:yMax,stroke:'#222','stroke-width':1,'vector-effect':'non-scaling-stroke'}));
      }
      const placedLabels=[], pointPositions=model.objects.filter(object=>object.kind==='point'&&object.visible).map(object=>point(object.name)).filter(Boolean);
      for (const object of model.objects) {
        if (!object.visible||object.kind==='point') continue;
        const path=object.kind==='conicpart'?pathFor(object):null, circle=circleGeometry(object.name);
        if (path) geometryLayer.append(node('path',{d:path,...styleFor(object)}));
        else if (circle) geometryLayer.append(node('circle',{cx:circle.center[0],cy:circle.center[1],r:circle.radius,...styleFor(object)}));
        else { const fallbackPath=pathFor(object); if (fallbackPath) geometryLayer.append(node('path',{d:fallbackPath,...styleFor(object)})); else if (['line','segment','ray','vector','polygon','polyline','conic','conicpart'].includes(object.kind)) unsupported.add(object.name); }
      }
      for (const object of model.objects) {
        if (object.kind!=='point'||!object.visible) continue; const position=point(object.name); if (!position) continue;
        const movable=movableNames.includes(object.name), radius=(movable?0.006:0.0045)*Math.max(spanX,spanY);
        const handle=node('circle',{cx:position[0],cy:position[1],r:radius,fill:'#111',stroke:movable?'#fff':'none','stroke-width':movable?1.5:0,'vector-effect':'non-scaling-stroke','data-point':object.name,style:movable?'cursor:grab':''});
        geometryLayer.append(handle);
        if (object.labelVisible) {
          const pixel=svg.clientWidth/spanX;
          const fontSize=Math.max(12,Math.min(20,svg.clientWidth/55));
          const layout=chooseLabelLayout(object,position,fontSize,pixel,placedLabels,pointPositions);
          const label=node('text',{x:layout.center[0],y:-layout.center[1],'font-size':fontSize/pixel,'font-family':'serif','font-style':'italic','text-anchor':'middle','dominant-baseline':'middle'});
          appendLabelContent(label,object.name); labelLayer.append(label); placedLabels.push(layout.box);
        }
      }
      unsupportedNode.textContent=unsupported.size?`暂未动态化：${[...unsupported].join('、')}（仍保留在静态 .asy 中）`:'';
      updateList();
    }
    function svgPoint(event) {
      const value=svg.createSVGPoint(); value.x=event.clientX; value.y=event.clientY;
      const transformed=value.matrixTransform(svg.getScreenCTM().inverse()); return [transformed.x,-transformed.y];
    }
    function updateList() {
      list.replaceChildren(...movableNames.map(name=>{ const row=document.createElement('li'), strong=document.createElement('strong'), value=document.createElement('span'); strong.textContent=name; const p=point(name); value.textContent=`(${p[0].toFixed(4)}, ${p[1].toFixed(4)})`; row.append(strong,value); return row; }));
    }
    svg.addEventListener('pointerdown',event=>{ const target=event.target.closest('[data-point]'); if (!target||!movableNames.includes(target.dataset.point)) return; activePoint=target.dataset.point; svg.setPointerCapture(event.pointerId); event.preventDefault(); });
    svg.addEventListener('pointermove',event=>{ if (!activePoint) return; points.set(activePoint,constrainMovable(activePoint,svgPoint(event))); render(); });
    svg.addEventListener('pointerup',event=>{ activePoint=null; if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId); });
    document.querySelector('#reset').addEventListener('click',()=>{ pathParameters.clear(); for (const [name,value] of initial) points.set(name,[...value]); render(); });
    new ResizeObserver(render).observe(svg); render();
  })();
  </script>
</body>
</html>'''
