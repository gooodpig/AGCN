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

pair A = (1.7320508, 1.8938086);
pair B = (-0.97677045, 0.82581666);
pair C = (1.7320508, 0);
pair a = (0.37764018, 0.41290833);
pair D = (1.0325083, 0.80289614);
pair pE = (-0.12199785, -0.99751634);
pair F = (0.87150678, 0.55181986);
pair M = (0.20756825, -0.99279327);
pair pN = (1.3029925, -0.65884006);
pair Dp = (2.4315933, 0.80289614);
pair Q = (1.7320508, 0.30968286);
pair P = (3.161024, -0.092396841);

real coniceq1(real x, real y) { return 0.33333333*x^2+1*y^2+0*x*y+0*x+0*y-1; }

// 画布范围
draw(box((-1.3742592, -1.3389911), (3.4969709, 2.2297555)), invisible);

// 曲线与直线
draw(contour(coniceq1, (-3.8288688, -3.0010446), (8.4146959, 3.4849053), new real[] {0}, 120), thinline);
draw((1.7320508, -3.0010446)--(1.7320508, 3.4849053), thinline);
draw(circle(a, abs(B-a)), thinline);
draw((-1.406751, -3.0010446)--(2.7523342, 3.4849053), thinline);
draw(F--C, thinline);
draw((-2.9636756, -3.0010446)--(6.2355855, 3.4849053), thinline);
draw((-3.8288688, 1.8743958)--(8.4146959, -1.5706574), thinline);
draw((-3.8288688, -2.2233495)--(8.4146959, 1.5092481), thinline);

// 坐标轴
draw((-3.8288688, 0)--(8.4146959, 0), axispen, Arrow(3));
draw((0, -3.0010446)--(0, 3.4849053), axispen, Arrow(3));
label("$x$", (8.4146959, 0), E);
label("$y$", (0, 3.4849053), N);

// 点与标签
label("$A$", A, E);
label("$B$", B, SE);dot(B, dotpen);
label("$C$", C, E);
label("$a$", a, W);dot(a, dotpen);
label("$D$", D, SE);dot(D, rgb(0.082352941,0.39607843,0.75294118)+dotpen);
label("$E$", pE, S);
label("$F$", F, 1.5*SW);
label("$M$", M, S);dot(M, dotpen);
label("$N$", pN, SE);dot(pN, dotpen);
label("$Q$", Q, E);
label("$P$", P, S);

clip(box((-1.3742592, -1.3389911), (3.4969709, 2.2297555)));
