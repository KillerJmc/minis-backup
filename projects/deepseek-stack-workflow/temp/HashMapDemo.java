import java.util.ArrayList;
import java.util.List;

/** 拉链法 HashMap：数组 + 单链表，负载因子 0.75，超了就翻倍扩容。 */
public class HashMapDemo {

    static final class Node {
        final int key;
        String val;
        Node next;
        Node(int k, String v) { key = k; val = v; }
    }

    private Node[] slots;
    private int size;
    private static final double LOAD = 0.75;

    HashMapDemo(int cap) { slots = new Node[cap]; }

    int size() { return size; }
    int capacity() { return slots.length; }

    /** key 走 hash 扰动后取模，和 JDK 的做法一致：h ^ (h >>> 16)。 */
    private int idx(int key, int cap) {
        int h = key ^ (key >>> 16);
        return h & (cap - 1);
    }

    String put(int key, String val) {
        int i = idx(key, slots.length);
        for (Node p = slots[i]; p != null; p = p.next) {
            if (p.key == key) { String old = p.val; p.val = val; return old; }
        }
        Node n = new Node(key, val);
        n.next = slots[i];
        slots[i] = n;
        if (++size > slots.length * LOAD) resize();
        return null;
    }

    String get(int key) {
        for (Node p = slots[idx(key, slots.length)]; p != null; p = p.next) {
            if (p.key == key) return p.val;
        }
        return null;
    }

    String remove(int key) {
        int i = idx(key, slots.length);
        Node prev = null;
        for (Node p = slots[i]; p != null; prev = p, p = p.next) {
            if (p.key != key) continue;
            if (prev == null) slots[i] = p.next;
            else prev.next = p.next;
            size--;
            return p.val;
        }
        return null;
    }

    private void resize() {
        Node[] old = slots;
        slots = new Node[old.length * 2];
        size = 0;
        for (Node head : old) {
            for (Node p = head; p != null; ) {
                Node next = p.next;
                p.next = null;
                int i = idx(p.key, slots.length);
                p.next = slots[i];
                slots[i] = p;
                size++;
                p = next;
            }
        }
    }

    /** 桶结构：0 -> [3,A] -> [11,B] 这种形式一眼能看出冲突链。 */
    String dump() {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < slots.length; i++) {
            if (slots[i] == null) continue;
            sb.append(String.format("  桶[%2d] ", i));
            for (Node p = slots[i]; p != null; p = p.next) {
                sb.append("[").append(p.key).append(",").append(p.val).append("]");
                if (p.next != null) sb.append(" -> ");
            }
            sb.append("\n");
        }
        return sb.toString();
    }

    private static int checks, fails;

    private static void expect(String what, Object want, Object got) {
        checks++;
        boolean ok = String.valueOf(want).equals(String.valueOf(got));
        if (!ok) fails++;
        System.out.printf("  %s %-28s 期望 %-8s 实际 %s%n", ok ? "✔" : "✘", what, want, got);
    }

    public static void main(String[] args) {
        HashMapDemo m = new HashMapDemo(4);
        System.out.println("初始容量 4，负载因子 0.75（size > 3 就扩容）");

        System.out.println("\n=== put ===");
        int[][] kv = {{1, 0}, {5, 0}, {9, 0}, {2, 0}};
        String[] labels = {"A", "B", "C", "D"};
        for (int i = 0; i < kv.length; i++) {
            m.put(kv[i][0], labels[i]);
            System.out.printf("put(%d,%s)  size=%d  容量=%d%n", kv[i][0], labels[i], m.size(), m.capacity());
        }

        System.out.println("\n=== 桶结构（1/5/9 都落在桶 1，形成冲突链）===");
        System.out.print(m.dump());

        System.out.println("\n=== get ===");
        System.out.println("get(5) = " + m.get(5));
        System.out.println("get(9) = " + m.get(9));
        System.out.println("get(7) = " + m.get(7) + "（不存在）");

        System.out.println("\n=== remove(5) ===");
        System.out.println("返回旧值 " + m.remove(5) + "，size=" + m.size());
        System.out.print(m.dump());

        System.out.println("\n=== 扩容：再放 4 个 ===");
        for (int k : new int[]{13, 21, 33, 41}) {
            m.put(k, "x" + k);
            System.out.printf("put(%d)  size=%d  容量=%d%n", k, m.size(), m.capacity());
        }
        System.out.print(m.dump());

        System.out.println("\n=== 断言 ===");
        expect("size", 7, m.size());
        expect("容量已翻倍", 16, m.capacity());
        expect("get(5) 已删", null, m.get(5));
        expect("get(9)", "C", m.get(9));
        expect("get(13)", "x13", m.get(13));
        expect("get(0) 不存在", null, m.get(0));
        expect("重复 put 返回旧值", "A", m.put(1, "A2"));
        expect("覆盖后 get(1)", "A2", m.get(1));

        System.out.printf("%n共 %d 个用例，失败 %d 个%n", checks, fails);
        if (fails > 0) System.exit(1);
    }
}
