import java.util.Random;

/** HashSet（数组版）：开放寻址 + 线性探测 + 墓碑删除，负载 0.5 扩容。 */
public class HashSetArrayDemo {

    private int[] keys;
    private boolean[] used;   // 该槽从未被占用
    private boolean[] dead;   // 已被删除，是墓碑
    private int size;
    private int deadCount;
    private static final double LOAD = 0.5;

    HashSetArrayDemo() {
        keys = new int[8];
        used = new boolean[8];
        dead = new boolean[8];
    }

    int size() { return size; }
    int capacity() { return keys.length; }

    private int hash(int k) {
        int h = Integer.hashCode(k) * 0x9E3779B1;
        return (h ^ (h >>> 16)) & (keys.length - 1);
    }

    private int[] probe = new int[64];

    boolean add(int key) {
        int n = 0, firstDead = -1, start = hash(key), mask = keys.length - 1;
        for (int step = 0; step < keys.length; step++) {
            int idx = (start + step) & mask;
            probe[n++] = idx;
            if (!used[idx]) {
                int put = firstDead >= 0 ? firstDead : idx;
                keys[put] = key; used[put] = true; dead[put] = false;
                size++;
                if ((size + deadCount) * 2 > keys.length) resize();
                return true;
            }
            if (dead[idx]) { if (firstDead < 0) firstDead = idx; continue; }
            if (keys[idx] == key) return false;
        }
        if (firstDead >= 0) {
            keys[firstDead] = key; used[firstDead] = true; dead[firstDead] = false;
            size++;
            return true;
        }
        return false;
    }

    /** 探测轨迹，调试用：返回访问过的槽位。 */
    String trace(int key) {
        int n = 0, start = hash(key), mask = keys.length - 1;
        StringBuilder sb = new StringBuilder();
        for (int step = 0; step < keys.length; step++) {
            int idx = (start + step) & mask;
            if (n++ > 0) sb.append(" → ");
            sb.append(idx);
            if (!used[idx] || (used[idx] && !dead[idx] && keys[idx] == key)) break;
        }
        return sb.toString();
    }

    boolean contains(int key) {
        int start = hash(key), mask = keys.length - 1;
        for (int step = 0; step < keys.length; step++) {
            int idx = (start + step) & mask;
            if (!used[idx]) return false;          // 遇到真空位，说明没这个 key
            if (!dead[idx] && keys[idx] == key) return true;
        }
        return false;
    }

    boolean remove(int key) {
        int start = hash(key), mask = keys.length - 1;
        for (int step = 0; step < keys.length; step++) {
            int idx = (start + step) & mask;
            if (!used[idx]) return false;
            if (!dead[idx] && keys[idx] == key) {
                dead[idx] = true; size--; deadCount++;
                return true;
            }
        }
        return false;
    }

    private void resize() {
        int[] ok = keys;
        boolean[] ou = used, od = dead;
        keys = new int[ok.length * 2];
        used = new boolean[keys.length];
        dead = new boolean[keys.length];
        size = 0; deadCount = 0;
        for (int i = 0; i < ok.length; i++)
            if (ou[i] && !od[i]) add(ok[i]);
    }

    void dump() {
        for (int i = 0; i < keys.length; i++) {
            String cell = !used[i] ? "空" : (dead[i] ? "墓碑" : String.valueOf(keys[i]));
            System.out.printf("  槽[%2d] %s%n", i, cell);
        }
    }

    public static void main(String[] args) {
        HashSetArrayDemo s = new HashSetArrayDemo();
        System.out.println("初始容量 " + s.capacity() + "，负载因子 0.5（开放寻址需要更空）");

        System.out.println("\n=== add：5 / 13 / 21 哈希后都落在槽 5，必须线性探测 ===");
        for (int k : new int[]{5, 13, 21, 29}) {
            System.out.printf("add(%2d) 探测路径 %-12s → %s  size=%d%n",
                    k, s.trace(k), s.add(k), s.size());
        }

        System.out.println("\n=== 槽位分布 ===");
        s.dump();

        System.out.println("\n=== contains ===");
        System.out.println("contains(21) = " + s.contains(21));
        System.out.println("contains(7)  = " + s.contains(7));

        System.out.println("\n=== remove(13) 留墓碑 ===");
        System.out.println("remove(13) = " + s.remove(13));
        s.dump();

        System.out.println("\n=== 墓碑不影响后续查找 ===");
        System.out.println("contains(21) = " + s.contains(21) + "（13 的墓碑被越过）");
        System.out.println("add(13) = " + s.add(13) + "（复用墓碑位置）");

        System.out.println("\n=== 扩容 ===");
        for (int k = 100; k < 106; k++) s.add(k);
        System.out.println("容量=" + s.capacity() + " size=" + s.size());

        int pass = 0, total = 0;
        total++; if (s.contains(21)) pass++;
        total++; if (s.contains(13)) pass++;
        total++; if (!s.contains(999)) pass++;

        Random rnd = new Random(5);
        boolean ok = true;
        for (int t = 0; t < 200; t++) {
            HashSetArrayDemo mine = new HashSetArrayDemo();
            java.util.HashSet<Integer> ref = new java.util.HashSet<>();
            for (int i = 0; i < 40; i++) {
                int k = rnd.nextInt(60), op = rnd.nextInt(3);
                if (op == 0) { if (mine.add(k) != ref.add(k)) { ok = false; break; } }
                else if (op == 1) { if (mine.remove(k) != ref.remove(k)) { ok = false; break; } }
                else if (mine.contains(k) != ref.contains(k)) { ok = false; break; }
            }
            if (!ok || mine.size() != ref.size()) { ok = false; break; }
        }
        total++; if (ok) pass++;

        System.out.printf("%n共 %d 个用例，失败 %d 个%n", total, total - pass);
        if (pass != total) System.exit(1);
    }
}
