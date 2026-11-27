/** 数组实现的链表（静态链表）：data 存值，next 存下标，-1 表示结束。 */
public class ArrayLinkedList {
    private final int[] data;
    private final int[] next;
    private final int cap;
    private int head = -1;
    private int free = 0;
    private int size = 0;

    ArrayLinkedList(int cap) {
        this.cap = cap;
        data = new int[cap];
        next = new int[cap];
        for (int i = 0; i < cap - 1; i++) next[i] = i + 1;
        next[cap - 1] = -1;
    }

    private int alloc() {
        if (free == -1) throw new IllegalStateException("数组已满");
        int p = free;
        free = next[p];
        return p;
    }

    private void release(int p) {
        next[p] = free;
        free = p;
    }

    boolean addLast(int v) {
        if (free == -1) return false;
        int p = alloc();
        data[p] = v;
        next[p] = -1;
        if (head == -1) {
            head = p;
        } else {
            int cur = head;
            while (next[cur] != -1) cur = next[cur];
            next[cur] = p;
        }
        size++;
        return true;
    }

    boolean remove(int v) {
        int prev = -1, cur = head;
        while (cur != -1 && data[cur] != v) {
            prev = cur;
            cur = next[cur];
        }
        if (cur == -1) return false;
        if (prev == -1) head = next[cur];
        else next[prev] = next[cur];
        release(cur);
        size--;
        return true;
    }

    int size() { return size; }

    String chain() {
        StringBuilder sb = new StringBuilder();
        for (int cur = head; cur != -1; cur = next[cur]) sb.append(data[cur]).append(" → ");
        return sb.append("null").toString();
    }

    String table() {
        StringBuilder sb = new StringBuilder("  下标 | 值 | next\n");
        for (int i = 0; i < cap; i++) {
            sb.append(String.format("   %2d  | %2s | %2s%n", i,
                    only(i) ? String.valueOf(data[i]) : "·", next[i]));
        }
        return "  head=" + head + "  free=" + free + "\n" + sb;
    }

    private boolean only(int i) {
        for (int cur = head; cur != -1; cur = next[cur]) if (cur == i) return true;
        return false;
    }

    public static void main(String[] args) {
        ArrayLinkedList list = new ArrayLinkedList(8);
        System.out.println("容量 8，依次插入 10, 20, 30");
        for (int v : new int[]{10, 20, 30}) { list.addLast(v); System.out.printf("addLast(%d) → %s%n", v, list.chain()); }
        System.out.println();
        System.out.println("删除 20");
        System.out.println("remove(20) = " + list.remove(20) + " → " + list.chain());
        System.out.println();
        System.out.println("插入 40");
        list.addLast(40);
        System.out.println("addLast(40) → " + list.chain());
        System.out.println();
        System.out.println("数组内部状态：");
        System.out.print(list.table());
        System.out.println();
        System.out.println("断言：");
        System.out.println("  size = " + list.size() + "（期望 3）" + (list.size() == 3 ? " ✔" : " ✘"));
        System.out.println("  chain = " + list.chain() + (list.chain().equals("10 → 30 → 40 → null") ? "✔" : " ✘"));
        System.out.println("  删不存在的 99 = " + list.remove(99) + (list.remove(99) == false ? " ✔" : " ✘"));
    }
}