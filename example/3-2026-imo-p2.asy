usepackage("amsmath");
size(8cm, keepAspect=true);
import graph;
import geometry;
import olympiad;

pen thinline = linewidth(0.5);
pen axispen = linewidth(0.2);
pen dotpen = linewidth(1) + black;
defaultpen(fontsize(8));

pair A = (-7.8173554, 10.70314);
pair B = (-12.28, 1.18);
pair C = (-5.3294744, 1.2613314);
pair M = (-10.048678, 5.9415702);
pair pN = (-6.5734149, 5.982236);
pair Q = (-10.536416, 4.9007523);
pair P = (-6.058745, 4.0290015);
pair K = (-10.111309, 2.1731445);
pair L = (-6.5898366, 2.1422686);
pair V = (-9.1768857, 7.8019464);
pair U = (-6.9380502, 7.366071);
pair R = (-4.0440043, 4.9516448);
pair pS = (-12.777419, 6.467114);
pair X = (-5.6941097, 2.6451665);
pair Y = (-11.408208, 3.0403762);
pair pO = (-8.3145743, 6.2634046);

// 画布范围
draw(box((-14.622987, -2.6985347), (-2.85231, 11.725669)), invisible);

// 曲线与直线
draw(A--B, thinline);
draw(B--C, thinline);
draw(C--A, thinline);
draw(circle(Q, B, C), dashed+thinline);
draw(circle(pN, P, B), dashed+thinline);
draw(circle(M, Q, C), dashed+thinline);
draw(P--B, thinline);
draw(Q--C, thinline);
draw(circle(A, L, K), thinline);

// 点与标签
label("$A$", A, 1.25*N);
label("$B$", B, SW);
label("$C$", C, SE);
label("$M$", M, SE);
label("$N$", pN, NE);
label("$Q$", Q, NW);
label("$P$", P, NE);
label("$K$", K, 2.5*S);
label("$L$", L, 2.5*S);
label("$V$", V, 1.5*NW);
label("$U$", U, NE);
label("$R$", R, 1.25*E);
label("$S$", pS, NW);
label("$X$", X, SW);
label("$Y$", Y, 2*E);
label("$O$", pO, E);dot(pO, dotpen);

clip(box((-14.622987, -2.6985347), (-2.85231, 11.725669)));
