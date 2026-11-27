import java.util.Random;

/** HashSet：拉链法解决冲突，负载 0.75 扩容，元素只存 key。 */
public class HashSetDemo {

    private static final class Node {
        final int key;
        Node next;
        Node(int k, Node n) { key = k; next = n; }
    }

    private Node[] buckets;
    private int size;
    private static final double LOAD = 0.75;

    HashSetDemo() { buckets = new Node[4]; }

    int size() { return size; }
    int capacity() { return buckets.length; }

    private int hash(int k) {
        int h = Integer.hashCode(k);
        return (h ^ (h >>> 16)) & (buckets.length - 1);
    }

    boolean add(int key) {
        if (contains(key)) return false;
        if (size + 1 > buckets.length * LOAD) resize();
        int i = hash(key);
        buckets[i] = new Node(key, buckets[i]);
        size++;
        return true;
    }

    boolean contains(int key) {
        for (Node p = buckets[hash(key)]; p != null; p = p.next)
            if (p.key == key) return true;
        return false;
    }

    boolean remove(int key) {
        int i = hash(key);
        Node prev = null;
        for (Node p = buckets[i]; p != null; prev = p, p = p.next) {
            if (p.key != key) continue;
            if (prev == null) buckets[i] = p.next; else prev.next = p.next;
            size--;
            return true;
        }
        return false;
    }

    private void resize() {
        Node[] old = buckets;
        buckets = new Node[old.length * 2];
        size = 0;
        for (Node head : old)
            for (Node p = head; p != null; p = p.next) {
                int i = hash(p.key);
                buckets[i] = new Node(p.key, buckets[i]);
                size++;
            }
    }

    void dump() {
        for (int i = 0; i < buckets.length; i++) {
            StringBuilder sb = new StringBuilder(String.format("  桶[%2d] ", i));
            if (buckets[i] == null) { sb.append("·"); }
            for (Node p = buckets[i]; p != null; p = p.next)
                sb.append(p.key).append(" -> ");
            System.out.println(sb);
        }
    }

    public static void main(String[] args) {
        HashSetDemo s = new HashSetDemo();
        System.out.println("初始容量 " + s.capacity() + "，负载因子 0.75");

        System.out.println("\n=== add ===");
        int[] keys = {5, 3, 13, 21, 8, 8};
        for (int k : keys) {
            boolean added = s.add(k);
            System.out.printf("add(%2d) = %-5s size=%d 容量=%d%n",
                    k, added, s.size(), s.capacity());
        }

        System.out.println("\n=== 桶结构（3/5/13/21 有冲突）===");
        s.dump();

        System.out.println("\n=== contains ===");
        System.out.println("contains(13) = " + s.contains(13));
        System.out.println("contains(4)  = " + s.contains(4));

        System.out.println("\n=== remove ===");
        System.out.println("remove(13) = " + s.remove(13) + "  size=" + s.size());
        System.out.println("remove(13) = " + s.remove(13) + "（再次删除）");
        s.dump();

        int pass = 0, total = 0;
        total++; if (s.size() == 4) pass++;
        total++; if (!s.contains(13)) pass++;
        total++; if (s.contains(21)) pass++;
        total++; if (s.add(5) == false) pass++;

        Random rnd = new Random(11);
        boolean ok = true;
        for (int t = 0; t < 200; t++) {
            HashSetDemo mine = new HashSetDemo();
            java.util.HashSet<Integer> ref = new java.util.HashSet<>();
            for (int i = 0; i < 40; i++) {
                int k = rnd.nextInt(50);
                int op = rnd.nextInt(3);
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
