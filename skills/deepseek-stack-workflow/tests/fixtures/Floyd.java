import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/** 沙盒样例：Floyd 全源最短路 + 路径还原。测试会真的编译运行它。 */
public class Floyd {

    static final long INF = Long.MAX_VALUE / 4;

    static final class Result {
        final long[][] dist;
        final int[][] next;

        Result(long[][] dist, int[][] next) {
            this.dist = dist;
            this.next = next;
        }

        List<Integer> path(int from, int to) {
            if (dist[from][to] == INF) {
                return null;
            }
            List<Integer> out = new ArrayList<>();
            out.add(from);
            int cur = from;
            while (cur != to) {
                cur = next[cur][to];
                out.add(cur);
            }
            return out;
        }
    }

    static Result solve(int n, int[][] edges) {
        long[][] d = new long[n][n];
        int[][] next = new int[n][n];
        for (int i = 0; i < n; i++) {
            Arrays.fill(d[i], INF);
            Arrays.fill(next[i], -1);
            d[i][i] = 0;
            next[i][i] = i;
        }
        for (int[] e : edges) {
            if (e[2] < d[e[0]][e[1]]) {
                d[e[0]][e[1]] = e[2];
                next[e[0]][e[1]] = e[1];
            }
        }
        for (int k = 0; k < n; k++) {
            for (int i = 0; i < n; i++) {
                if (d[i][k] == INF) continue;
                for (int j = 0; j < n; j++) {
                    if (d[k][j] == INF) continue;
                    long through = d[i][k] + d[k][j];
                    if (through < d[i][j]) {
                        d[i][j] = through;
                        next[i][j] = next[i][k];
                    }
                }
            }
        }
        return new Result(d, next);
    }

    static long[][] allPairs(int n, int[][] edges) {
        return solve(n, edges).dist;
    }

    private static int checks = 0;

    private static void expect(int n, int[][] edges, int from, int to, long want) {
        long[][] d = allPairs(n, edges);
        checks++;
        if (d[from][to] != want) {
            throw new AssertionError("用例 " + checks + " 失败：" + from + "→" + to
                + " 期望 " + want + "，实际 " + d[from][to]);
        }
    }

    /** 路径逐边求和必须等于距离矩阵，防止「压缩路径」冒充真实路径。 */
    private static void expectPath(int n, int[][] edges, int from, int to) {
        Result r = solve(n, edges);
        List<Integer> p = r.path(from, to);
        checks++;
        if (p == null) {
            throw new AssertionError("用例 " + checks + " 失败：路径为空");
        }
        long sum = 0;
        for (int i = 0; i + 1 < p.size(); i++) {
            int a = p.get(i), b = p.get(i + 1);
            long w = INF;
            for (int[] e : edges) {
                if (e[0] == a && e[1] == b) w = Math.min(w, e[2]);
            }
            if (w == INF) {
                throw new AssertionError("用例 " + checks + " 失败：路径含不存在的边 " + a + "→" + b);
            }
            sum += w;
        }
        if (sum != r.dist[from][to]) {
            throw new AssertionError("用例 " + checks + " 失败：" + from + "→" + to
                + " 路径 " + p + " 边权和 " + sum + "，矩阵值 " + r.dist[from][to]);
        }
    }

    public static void main(String[] args) {
        int[][] g1 = {{0, 1, 4}, {0, 2, 1}, {2, 1, 2}, {1, 3, 1}, {2, 3, 5}};
        expect(4, g1, 0, 3, 4);
        expect(4, g1, 0, 1, 3);
        expect(4, g1, 3, 0, INF);
        expect(4, g1, 2, 2, 0);
        expectPath(4, g1, 0, 3);

        int[][] g2 = {{0, 1, 10}, {0, 2, 1}, {2, 1, 2}};
        expect(3, g2, 0, 1, 3);
        expectPath(3, g2, 0, 1);

        int[][] g3 = {{0, 1, 5}, {0, 1, 2}};
        expect(2, g3, 0, 1, 2);

        int[][] g4 = {{0, 1, 2}, {1, 2, -1}, {0, 2, 5}};
        expect(3, g4, 0, 2, 1);

        System.out.println("共 " + checks + " 个用例，失败 0 个");
    }
}
