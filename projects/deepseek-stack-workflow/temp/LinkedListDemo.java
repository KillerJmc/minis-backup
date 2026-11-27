import java.util.ArrayList;
import java.util.List;

/**
 * 单链表演示：增删查 + 反转，每一步打印结构图。
 * 运行：javac -d /tmp/ll LinkedListDemo.java && java -cp /tmp/ll LinkedListDemo
 */
public class LinkedListDemo {

    static final class Node {
        final int val;
        Node next;
        Node(int val) { this.val = val; }
    }

    static final class SinglyLinkedList {
        private Node head;
        private int size;

        /** 尾部追加。 */
        void addLast(int val) {
            Node n = new Node(val);
            size++;
            if (head == null) { head = n; return; }
            Node cur = head;
            while (cur.next != null) cur = cur.next;
            cur.next = n;
        }

        /** 头部插入。 */
        void addFirst(int val) {
            Node n = new Node(val);
            n.next = head;
            head = n;
            size++;
        }

        /** 删除第一个值为 val 的节点，返回是否删到。 */
        boolean remove(int val) {
            Node prev = null, cur = head;
            while (cur != null && cur.val != val) {
                prev = cur;
                cur = cur.next;
            }
            if (cur == null) return false;
            if (prev == null) head = cur.next;
            else prev.next = cur.next;
            size--;
            return true;
        }

        boolean contains(int val) {
            for (Node cur = head; cur != null; cur = cur.next) {
                if (cur.val == val) return true;
            }
            return false;
        }

        int size() { return size; }

        /** 原地反转，返回反转后的头。 */
        Node reverse() {
            Node prev = null, cur = head;
            while (cur != null) {
                Node next = cur.next;
                cur.next = prev;
                prev = cur;
                cur = next;
            }
            head = prev;
            return head;
        }

        List<Integer> toList() {
            List<Integer> out = new ArrayList<>();
            for (Node cur = head; cur != null; cur = cur.next) out.add(cur.val);
            return out;
        }

        /** 可读的结构图：1 → 2 → 3 → null */
        @Override public String toString() {
            StringBuilder sb = new StringBuilder();
            for (Node cur = head; cur != null; cur = cur.next) {
                sb.append(cur.val).append(" → ");
            }
            return sb.append("null").toString();
        }
    }

    private static int cases, failed;

    private static void expect(String what, Object want, Object got) {
        cases++;
        boolean ok = want.equals(got);
        if (!ok) failed++;
        System.out.printf("  %s %-34s 期望 %-18s 实际 %s%n",
                ok ? "✔" : "✘", what, want, got);
    }

    public static void main(String[] args) {
        SinglyLinkedList list = new SinglyLinkedList();

        System.out.println("=== 1. 依次追加 3, 7, 1, 9 ===");
        for (int v : new int[]{3, 7, 1, 9}) {
            list.addLast(v);
            System.out.printf("addLast(%d)  →  %s   （size=%d）%n", v, list, list.size());
        }

        System.out.println();
        System.out.println("=== 2. 头部插入 5 ===");
        list.addFirst(5);
        System.out.printf("addFirst(5) →  %s   （size=%d）%n", list, list.size());

        System.out.println();
        System.out.println("=== 3. 查找 ===");
        System.out.printf("contains(7) = %s%n", list.contains(7));
        System.out.printf("contains(4) = %s%n", list.contains(4));

        System.out.println();
        System.out.println("=== 4. 删除 1（中间节点）===");
        System.out.printf("remove(1) = %s  →  %s   （size=%d）%n",
                list.remove(1), list, list.size());

        System.out.println();
        System.out.println("=== 5. 删除 5（头节点）===");
        System.out.printf("remove(5) = %s  →  %s   （size=%d）%n",
                list.remove(5), list, list.size());

        System.out.println();
        System.out.println("=== 6. 反转 ===");
        System.out.printf("反转前  %s%n", list);
        list.reverse();
        System.out.printf("反转后  %s   （size=%d）%n", list, list.size());

        System.out.println();
        System.out.println("=== 断言 ===");
        expect("size", 3, list.size());
        expect("遍历顺序", List.of(9, 7, 3), list.toList());
        expect("反转后头结点", 9, list.toList().get(0));
        expect("contains(7)", true, list.contains(7));
        expect("contains(1)（已删）", false, list.contains(1));

        SinglyLinkedList one = new SinglyLinkedList();
        one.addLast(42);
        one.reverse();
        expect("单节点反转", List.of(42), one.toList());

        SinglyLinkedList empty = new SinglyLinkedList();
        empty.reverse();
        expect("空链表反转", List.of(), empty.toList());
        expect("空链表删除", false, empty.remove(1));

        System.out.printf("%n共 %d 个用例，失败 %d 个%n", cases, failed);
        if (failed > 0) System.exit(1);
    }
}
