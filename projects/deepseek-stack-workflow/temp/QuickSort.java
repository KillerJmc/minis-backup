import java.util.Arrays;
import java.util.Random;

/** 快速排序：三数取中选基准 + Hoare 双指针分区 + 小区间插排。 */
public class QuickSort {

    static long cmp = 0;

    static void sort(int[] a) {
        cmp = 0;
        quickSort(a, 0, a.length - 1);
    }

    private static void quickSort(int[] a, int lo, int hi) {
        while (lo < hi) {
            if (hi - lo < 8) {
                insertion(a, lo, hi);
                return;
            }
            int p = partition(a, lo, hi);
            // 先递归较小的一侧，较大的一侧用循环消化，栈深稳定在 O(log n)
            if (p - lo < hi - p) {
                quickSort(a, lo, p);
                lo = p + 1;
            } else {
                quickSort(a, p + 1, hi);
                hi = p;
            }
        }
    }

    private static int partition(int[] a, int lo, int hi) {
        int mid = lo + (hi - lo) / 2;
        int pivot = medianOfThree(a, lo, mid, hi);
        int i = lo, j = hi;
        while (true) {
            while (a[i] < pivot) { i++; cmp++; }
            while (a[j] > pivot) { j--; cmp++; }
            if (i >= j) return j;
            swap(a, i++, j--);
        }
    }

    private static int medianOfThree(int[] a, int x, int y, int z) {
        if (a[x] > a[y]) swap(a, x, y);
        if (a[y] > a[z]) swap(a, y, z);
        if (a[x] > a[y]) swap(a, x, y);
        return a[y];
    }

    private static void insertion(int[] a, int lo, int hi) {
        for (int i = lo + 1; i <= hi; i++) {
            int v = a[i], j = i - 1;
            while (j >= lo && a[j] > v) { a[j + 1] = a[j]; j--; cmp++; }
            a[j + 1] = v;
        }
    }

    private static void swap(int[] a, int i, int j) {
        int t = a[i]; a[i] = a[j]; a[j] = t;
    }

    // ---------- 演示 ----------

    public static void main(String[] args) {
        int[] demo = {5, 3, 8, 1, 9, 2, 7, 6};
        System.out.println("原始数组：" + Arrays.toString(demo));
        sort(demo);
        System.out.println("排序结果：" + Arrays.toString(demo));
        System.out.println("比较次数：" + cmp + "（8 个元素）");
        System.out.println();

        System.out.println("=== 用例 ===");
        int pass = 0, total = 0;

        total++; if (check("重复元素", new int[]{3, 3, 1, 3, 2, 1})) pass++;
        total++; if (check("已有序", new int[]{1, 2, 3, 4, 5, 6, 7, 8, 9})) pass++;
        total++; if (check("逆序", new int[]{9, 8, 7, 6, 5, 4, 3, 2, 1})) pass++;
        total++; if (check("单元素", new int[]{42})) pass++;
        total++; if (check("空数组", new int[]{})) pass++;
        total++; if (check("全相同", new int[]{7, 7, 7, 7, 7, 7, 7, 7, 7, 7})) pass++;

        Random rnd = new Random(7);
        boolean allOk = true;
        for (int t = 0; t < 300; t++) {
            int n = rnd.nextInt(60);
            int[] a = new int[n];
            for (int i = 0; i < n; i++) a[i] = rnd.nextInt(200) - 100;
            int[] want = a.clone();
            Arrays.sort(want);
            sort(a);
            if (!Arrays.equals(a, want)) { allOk = false; break; }
        }
        total++; if (allOk) pass++;

        System.out.println();
        System.out.println("共 " + total + " 个用例，失败 " + (total - pass) + " 个");
        if (pass != total) System.exit(1);
    }

    private static boolean check(String name, int[] input) {
        int[] got = input.clone();
        int[] want = input.clone();
        Arrays.sort(want);
        sort(got);
        boolean ok = Arrays.equals(got, want);
        System.out.printf("  %s %-8s %s%n", ok ? "✔" : "✘", name, Arrays.toString(got));
        return ok;
    }
}
