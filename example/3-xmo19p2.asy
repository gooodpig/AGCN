usepackage("amsmath");
size(8cm, keepAspect=true);
import graph;
import geometry;
import olympiad;

pen thinline = linewidth(0.5);
pen axispen = linewidth(0.2);
pen dotpen = linewidth(1) + black;
defaultpen(fontsize(8));

pair B = (1.2137827, 1.5888128);
pair C = (2.1081711, 1.5888128);
pair H = (1.6308193, 1.5888128);
pair pE = (1.4657863, 1.7927464);
pair F = (1.8197207, 1.8222409);
pair A = (1.6308193, 2.3125954);
pair P = (1.6178477, 1.7444725);

// 画布范围
draw(box((1.1422316, 1.5172617), (2.1797222, 2.3842205)), invisible);

// 曲线与直线
draw(pE--B, thinline);
draw(F--C, thinline);
draw(C--B, thinline);
draw(F--B, thinline);
draw(pE--C, thinline);
draw(A--B, thinline);
draw(A--C, thinline);
draw(circle(A, pE, F), thinline);

// 锐角标记
draw(arc(B, 0.031124717, 38.981465, 60.049863), thinline);
draw(arc(B, 0.031124717, 0, 21.068398), thinline);
draw(arc(C, 0.031124717, 123.4058, 141.01853), thinline);
draw(arc(C, 0.031124717, 162.38727, 180), thinline);

// 点与标签
label("$B$", B, 1.5*SW);
label("$C$", C, 1.25*S);
label("$H$", H, 1.5*SW);dot(H, dotpen);
label("$E$", pE, 1.5*N);
label("$F$", F, 1.5*N);
label("$A$", A, 1.25*N);
label("$P$", P, 1.25*S);

clip(box((1.1422316, 1.5172617), (2.1797222, 2.3842205)));
