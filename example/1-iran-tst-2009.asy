usepackage("amsmath");
size(8cm, keepAspect=true);
import graph;
import geometry;
import olympiad;

pen thinline = linewidth(0.5);
pen axispen = linewidth(0.2);
pen dotpen = linewidth(1) + black;
defaultpen(fontsize(8));

pair A = (-3, 2);
pair B = (-3.9892683, -3);
pair C = (3.0107317, -3);
pair pI = (-1.8500539, -1.2425681);
pair D = (-1.8500539, -3);
pair pE = (-0.72616021, 0.10851666);
pair F = (-3.5740656, -0.90146605);
pair H = (-1.8500539, 2.9167369);
pair B_1 = (0.19005083, 0.43344224);
pair C_1 = (-3.1800106, -0.76171816);
pair pN = (-2.1501129, -0.39647469);
pair M = (-2.7037399, -0.59281327);
pair P = (-2.2768969, -1.7964066);
pair X_C = (-4.4483505, 1.3728643);
pair X_B = (0.74824268, 1.3728643);

// 画布范围
draw(box((-5.5875466, -3.7151281), (3.7258599, 6.6542296)), invisible);

// 曲线与直线
draw(A--B--C--cycle, rgb(0,0.6,0)+thinline);
draw(A--B, rgb(0,0.6,0)+thinline);
draw(B--C, rgb(0,0.6,0)+thinline);
draw(C--A, rgb(0,0.6,0)+thinline);
draw(circle(D, pE, F), rgb(0,0.6,0)+thinline);
draw(D--pE--F--cycle, dotted+rgb(0.2,0.4,0)+thinline);
draw(D--pE, dotted+rgb(0.2,0.4,0)+thinline);
draw(pE--F, dotted+rgb(0.2,0.4,0)+thinline);
draw(F--D, dotted+rgb(0.2,0.4,0)+thinline);
draw(B--C--H--cycle, rgb(0.6,0.2,0)+thinline);
draw(B--C, rgb(0.6,0.2,0)+thinline);
draw(C--H, rgb(0.6,0.2,0)+thinline);
draw(H--B, rgb(0.6,0.2,0)+thinline);
draw(B_1--C_1--D--cycle, rgb(0,0.4,0.4)+thinline);
draw(B_1--C_1, rgb(0,0.4,0.4)+thinline);
draw(C_1--D, rgb(0,0.4,0.4)+thinline);
draw(D--B_1, rgb(0,0.4,0.4)+thinline);
draw(D--M, thinline);
draw(circle((-1.8500539, -1.2425681), 0.89772457), rgb(0,0.4,0.4)+thinline);
draw(P--H, dashed+thinline);
draw(C_1--X_C, dashed+rgb(0,0,1)+thinline);
draw(B_1--X_B, dashed+rgb(0,0,1)+thinline);
draw(circle((-1.8500539, 2.9167369), 3.0223646), dashed+rgb(0.2,0,0.6)+thinline);

// 点与标签
label("$A$", A, NW);
label("$B$", B, SW);
label("$C$", C, SE);
label("$I$", pI, E);dot(pI, dotpen);
label("$D$", D, 1.25*S);
label("$E$", pE, 1.5*N);
label("$F$", F, 1.5*W);
label("$H$", H, NW);
label("$B_1$", B_1, 1.5*E);
label("$C_1$", C_1, SE);
label("$N$", pN, SE);
label("$M$", M, 1.25*N);
label("$P$", P, 1.25*E);

clip(box((-5.5875466, -3.7151281), (3.7258599, 6.6542296)));
