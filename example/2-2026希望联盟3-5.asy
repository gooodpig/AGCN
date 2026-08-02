usepackage("amsmath");
size(8cm, keepAspect=true);
import graph;
import geometry;
import olympiad;
import contour;

pen thinline = linewidth(0.5);
pen axispen = linewidth(0.2);
pen dotpen = linewidth(1) + black;
defaultpen(fontsize(8));

pair A = (-8.5438143, 8.8113744);
pair B = (-12.82, 3.74);
pair C = (-7.5230583, 3.7427931);
pair pE = (-11.311265, 5.5292953);
pair F = (-7.883204, 5.5311029);
pair a = (-8.5423776, 6.0869185);
pair M = (-9.5972346, 5.5301991);
pair aa = (-10.650655, 2.2490238);
pair D = (-10.432399, 3.741259);
pair P = (-2.2567679, 3.7455701);
pair pS = (-9.597953, 6.8924271);
pair pO = (-10.172639, 5.8462721);
pair K = (-6.3453018, 5.1056425);
pair Ap = (-10.652092, 4.9734797);
pair pN = (-6.3445835, 3.7434146);
pair H = (-9.5962915, 3.7416999);

real conicc(real x, real y) { return 48.896969*x^2-48.896969*y^2+178.24613*x*y-47.185216*x+2251.4899*y-6595.948; }

// 画布范围
draw(box((-13.682681, -0.065855949), (-1.1738033, 10.277141)), invisible);

// 曲线与直线
draw(A--B, thinline);
draw(A--C, thinline);
draw(contour(conicc, (-14.162403, 0.5539865), (2.7363961, 9.9240795), new real[] {0}, 120), rgb(0,1,1)+thinline);
draw(A--pS, thinline);
draw(pS--K, thinline);
draw(K--A, thinline);
draw(K--D, thinline);
draw(pS--Ap, dashed+thinline);
draw(pS--H, dashed+thinline);
draw(M--pN, dashed+thinline);
draw(pN--K, dashed+thinline);
draw(K--pO, dashed+thinline);
draw(K--Ap, dashed+thinline);
draw(B--P, thinline);
draw(circle(A, pE, F), dashed+thinline);
draw(circle(A, D, P), dashed+thinline);

// 点与标签
label("$A$", A, 1.25*NW);
label("$B$", B, SW);
label("$C$", C, S);
label("$E$", pE, 1.5*S);dot(pE, rgb(0.082352941,0.39607843,0.75294118)+dotpen);
label("$F$", F, 1.5*NE);dot(F, dotpen);
label("$M$", M, 1.5*NE);
label("$D$", D, 1.5*SW);
label("$P$", P, 1.5*NE);dot(P, dotpen);
label("$S$", pS, 1.5*E);
label("$O$", pO, 1.25*W);
label("$K$", K, NE);
label("$A'$", Ap, 1.5*SW);
label("$N$", pN, SE);
label("$H$", H, S);

clip(box((-13.682681, -0.065855949), (-1.1738033, 10.277141)));
