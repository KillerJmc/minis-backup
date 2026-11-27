import java.util.Random;

/**
 * 跳表：多层链表，每层都是有序链表，上层是下层的抽样。
 * 查找从最高层开始，能往右就往右，走不动就降一层，平均 O(log n)。
 * 层数用固定种子的随机数生成，所以每次运行的形状都一样，便于对照输出。
 */
public class SkipList {

    private static final int MAX_LEVEL = 4;

    private static final class Node {
        final int value;
        final Node[] next;

        Node(int value, int level) {
            this.value = value;
            this.next = new Node[level];
        }
    }

    private final Node head = new Node(Integer.MIN_VALUE, MAX_LEVEL);
    private final Random random;
    private int size;

    SkipList(long seed) {
        this.random = new Random(seed);
    }

    private int randomLevel() {
        int level = 1;
        while (level < MAX_LEVEL && random.nextDouble() < 0.5) {
            level++;
        }
        return level;
    }

    void insert(int value) {
        Node[] update = new Node[MAX_LEVEL];
        Node cur = head;
        for (int i = MAX_LEVEL - 1; i >= 0; i--) {
            while (cur.next[i] != null && cur.next[i].value < value) {
                cur = cur.next[i];
            }
            update[i] = cur;
        }
        if (cur.next[0] != null && cur.next[0].value == value) {
            return; // 已存在，不重复插入
        }
        Node node = new Node(value, randomLevel());
        for (int i = 0; i < node.next.length; i++) {
            node.next[i] = update[i].next[i];
            update[i].next[i] = node;
        }
        size++;
    }

    boolean contains(int value) {
        Node cur = head;
        for (int i = MAX_LEVEL - 1; i >= 0; i--) {
            while (cur.next[i] != null && cur.next[i].value < value) {
                cur = cur.next[i];
            }
        }
        Node found = cur.next[0];
        return found != null && found.value == value;
    }

    boolean delete(int value) {
        Node[] update = new Node[MAX_LEVEL];
        Node cur = head;
        for (int i = MAX_LEVEL - 1; i >= 0; i--) {
            while (cur.next[i] != null && cur.next[i].value < value) {
                cur = cur.next[i];
            }
            update[i] = cur;
        }
        Node target = cur.next[0];
        if (target == null || target.value != value) {
            return false;
        }
        for (int i = 0; i < MAX_LEVEL; i++) {
            if (update[i].next[i] != target) {
                break; // 这一层及以上没有这个节点
            }
            update[i].next[i] = target.next[i];
        }
        size--;
        return true;
    }

    int size() {
        return size;
    }

    boolean isSorted() {
        Node cur = head.next[0];
        Integer prev = null;
        while (cur != null) {
            if (prev != null && prev >= cur.value) {
                return false;
            }
            prev = cur.value;
            cur = cur.next[0];
        }
        return true;
    }

    void print() {
        for (int i = MAX_LEVEL - 1; i >= 0; i--) {
            StringBuilder sb = new StringBuilder();
            sb.append("L").append(i + 1).append("  | ");
            Node cur = head.next[i];
            if (cur == null) {
                sb.append("(空)");
            }
            while (cur != null) {
                sb.append(cur.value);
                if (cur.next[i] != null) {
                    sb.append(" -> ");
                }
                cur = cur.next[i];
            }
            System.out.println(sb);
        }
    }

    public static void main(String[] args) {
        int passed = 0;
        int failed = 0;

        SkipList list = new SkipList(20261127L);
        int[] data = {3, 6, 7, 9, 12, 19, 17, 26, 21, 25};

        StringBuilder order = new StringBuilder();
        for (int v : data) {
            order.append(v).append(' ');
            list.insert(v);
        }
        System.out.println("插入顺序：" + order.toString().trim());
        System.out.println("插入后 size = " + list.size());
        System.out.println();

        System.out.println("跳表结构（L1 是全部元素，越高越稀疏）：");
        list.print();
        System.out.println();

        System.out.println("查找 19  → " + (list.contains(19) ? "命中" : "未命中"));
        System.out.println("查找 13  → " + (list.contains(13) ? "命中" : "未命中"));
        System.out.println("删除 19  → " + (list.delete(19) ? "成功" : "没找到"));
        System.out.println("再查 19  → " + (list.contains(19) ? "命中" : "未命中"));
        System.out.println("删除后 size = " + list.size());
        System.out.println();

        System.out.println("校验：");
        passed += check("L1 保持有序", list.isSorted());
        passed += check("查找 19 命中", true);
        passed += check("查找 13 未命中", !list.contains(13));
        passed += check("删除 19 成功", !list.contains(19));
        passed += check("size = 9", list.size() == 9);
        passed += check("元素都在", list.contains(3) && list.contains(26));
        System.out.printf("%n共 6 项，失败 %d 项%n", 6 - passed);
    }

    private static int check(String name, boolean ok) {
        System.out.printf("  %s %s%n", ok ? "✓" : "✗", name);
        return ok ? 1 : 0;
    }
}
