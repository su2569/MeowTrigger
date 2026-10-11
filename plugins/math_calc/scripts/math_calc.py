"""
复杂数学计算器
 - AST 安全求值（只允许白名单节点 / 函数 / 常量）
 - 常量: pi, e, tau, phi, inf, nan, j
 - 函数: 三角/反三角/双曲/对数/指数/根/取整/组合/统计/进制/类型
 - 支持复数、分数、Decimal 大数
 - 参数: args（触发词后面的内容）
"""
import ast
import math
import statistics
from decimal import Decimal, getcontext
from fractions import Fraction

getcontext().prec = 50

# ==================== 常量 ====================
CONSTANTS = {
    "pi": math.pi, "e": math.e, "tau": math.tau,
    "inf": math.inf, "nan": math.nan,
    "phi": (1 + math.sqrt(5)) / 2,
    "j": 1j,
}


# ==================== 安全函数表 ====================
def _frac(num, den=1):
    return Fraction(num, den)


def _cbrt(x):
    return x ** (1 / 3) if x >= 0 else -((-x) ** (1 / 3))


FUNCTIONS = {
    # 三角
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "atan2": math.atan2,
    "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "asinh": math.asinh, "acosh": math.acosh, "atanh": math.atanh,
    "degrees": math.degrees, "radians": math.radians,
    "hypot": math.hypot, "dist": math.dist,
    # 对数 / 指数
    "log": lambda x, base=math.e: math.log(x, base),
    "log10": math.log10, "log2": math.log2, "log1p": math.log1p,
    "ln": math.log,
    "exp": math.exp, "expm1": math.expm1,
    "sqrt": math.sqrt, "isqrt": math.isqrt, "cbrt": _cbrt,
    # 取整
    "abs": abs, "fabs": math.fabs,
    "floor": math.floor, "ceil": math.ceil,
    "trunc": math.trunc, "round": round,
    # 组合
    "factorial": math.factorial, "gcd": math.gcd, "lcm": math.lcm,
    "comb": math.comb, "perm": math.perm, "prod": math.prod,
    # 数值
    "fsum": math.fsum, "fmod": math.fmod, "remainder": math.remainder,
    "copysign": math.copysign,
    # 统计
    "mean": statistics.mean,
    "median": statistics.median,
    "mode": statistics.mode,
    "stdev": statistics.stdev,
    "variance": statistics.variance,
    "pstdev": statistics.pstdev,
    "pvariance": statistics.pvariance,
    # 进制
    "hex": hex, "bin": bin, "oct": oct,
    # 类型 / 大数
    "int": int, "float": float, "complex": complex, "bool": bool,
    "Decimal": Decimal, "Fraction": Fraction, "frac": _frac,
    # 其它
    "min": min, "max": max, "sum": sum,
    "pow": pow, "len": len, "divmod": divmod,
}


# ==================== AST 安全求值 ====================
class SafeMathEvaluator(ast.NodeVisitor):
    MAX_DEPTH = 80
    MAX_POW = 10000

    def __init__(self):
        self.depth = 0

    def eval(self, expr: str):
        expr = expr.strip()
        if not expr:
            raise ValueError("表达式为空")
        if len(expr) > 10000:
            raise ValueError("表达式过长（>10000）")
        tree = ast.parse(expr, mode="eval")
        return self.visit(tree.body)

    def _enter(self):
        self.depth += 1
        if self.depth > self.MAX_DEPTH:
            raise RecursionError("表达式嵌套过深")

    def _exit(self):
        self.depth -= 1

    def visit_Constant(self, node):
        v = node.value
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float, complex)):
            return v
        if isinstance(v, str):
            return v
        raise ValueError(f"不支持的常量类型: {type(v).__name__}")

    visit_Num = visit_Constant  # 兼容旧 Python

    def visit_Name(self, node):
        if node.id in CONSTANTS:
            return CONSTANTS[node.id]
        if node.id in FUNCTIONS:
            return FUNCTIONS[node.id]
        raise NameError(f"未知名称: {node.id}")

    def visit_BinOp(self, node):
        self._enter()
        try:
            l = self.visit(node.left)
            r = self.visit(node.right)
        finally:
            self._exit()
        op = node.op
        if isinstance(op, ast.Add): return l + r
        if isinstance(op, ast.Sub): return l - r
        if isinstance(op, ast.Mult): return l * r
        if isinstance(op, ast.Div):
            if r == 0:
                raise ZeroDivisionError("除以零")
            return l / r
        if isinstance(op, ast.FloorDiv):
            if r == 0:
                raise ZeroDivisionError("整除零")
            return l // r
        if isinstance(op, ast.Mod):
            if r == 0:
                raise ZeroDivisionError("模零")
            return l % r
        if isinstance(op, ast.Pow):
            if isinstance(l, (int, float)) and isinstance(r, (int, float)):
                if abs(l) > 1 and r > self.MAX_POW:
                    raise ValueError(f"指数过大（>{self.MAX_POW}）")
            return l ** r
        raise ValueError(f"不支持的运算符: {type(op).__name__}")

    def visit_UnaryOp(self, node):
        v = self.visit(node.operand)
        if isinstance(node.op, ast.USub): return -v
        if isinstance(node.op, ast.UAdd): return +v
        if isinstance(node.op, ast.Not): return not v
        if isinstance(node.op, ast.Invert): return ~v
        raise ValueError(f"不支持的一元运算符: {type(node.op).__name__}")

    def visit_BoolOp(self, node):
        vals = [self.visit(v) for v in node.values]
        if isinstance(node.op, ast.And):
            r = vals[0]
            for v in vals[1:]:
                if not r:
                    return r
                r = v
            return r
        if isinstance(node.op, ast.Or):
            r = vals[0]
            for v in vals[1:]:
                if r:
                    return r
                r = v
            return r
        raise ValueError("不支持的布尔运算")

    def visit_Compare(self, node):
        left = self.visit(node.left)
        for op, comp in zip(node.ops, node.comparators):
            right = self.visit(comp)
            if isinstance(op, ast.Eq): ok = left == right
            elif isinstance(op, ast.NotEq): ok = left != right
            elif isinstance(op, ast.Lt): ok = left < right
            elif isinstance(op, ast.LtE): ok = left <= right
            elif isinstance(op, ast.Gt): ok = left > right
            elif isinstance(op, ast.GtE): ok = left >= right
            else:
                raise ValueError("不支持的比较运算符")
            if not ok:
                return False
            left = right
        return True

    def visit_Call(self, node):
        if not isinstance(node.func, ast.Name):
            raise ValueError("只允许调用简单函数名")
        fname = node.func.id
        if fname not in FUNCTIONS:
            raise NameError(f"未知函数: {fname}")
        self._enter()
        try:
            args_ = [self.visit(a) for a in node.args]
            kwargs = {k.arg: self.visit(k.value) for k in node.keywords if k.arg}
        finally:
            self._exit()
        fn = FUNCTIONS[fname]
        try:
            return fn(*args_, **kwargs)
        except Exception as e:
            raise RuntimeError(f"函数 {fname} 执行错误: {e}")

    def visit_Tuple(self, node):
        return tuple(self.visit(e) for e in node.elts)

    def visit_List(self, node):
        return [self.visit(e) for e in node.elts]

    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name) and node.value.id in CONSTANTS:
            obj = CONSTANTS[node.value.id]
            attr = node.attr
            if attr.startswith("_"):
                raise AttributeError(f"禁止访问私有属性: {attr}")
            return getattr(obj, attr)
        raise ValueError("不支持的属性访问")

    def visit_Subscript(self, node):
        v = self.visit(node.value)
        if isinstance(node.slice, ast.Constant):
            idx = node.slice.value
        elif hasattr(ast, "Index") and isinstance(node.slice, ast.Index):
            idx = self.visit(node.slice.value)
        else:
            idx = self.visit(node.slice)
        return v[idx]

    def generic_visit(self, node):
        raise ValueError(f"不支持的语法: {type(node).__name__}")


# ==================== 输出格式化 ====================
def format_result(v):
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        if abs(v) >= 10000:
            return f"{v:,}"
        return str(v)
    if isinstance(v, float):
        if math.isnan(v):
            return "nan"
        if math.isinf(v):
            return "inf" if v > 0 else "-inf"
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return f"{v:.10g}"
    if isinstance(v, complex):
        re = v.real
        im = v.imag
        if re == 0:
            return f"{format_result(im)}j"
        sign = "+" if im >= 0 else "-"
        return f"{format_result(re)} {sign} {format_result(abs(im))}j"
    if isinstance(v, Fraction):
        if v.denominator == 1:
            return str(v.numerator)
        return f"{v.numerator}/{v.denominator} ≈ {float(v):.10g}"
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(format_result(x) for x in v) + "]"
    return str(v)


# ==================== 主入口 ====================
def main():
    expr = (args or "").strip()
    if not expr and message:
        # 从 "/calc xxx" 或 "计算 xxx" 中提取
        m = message.strip()
        if m.startswith("/"):
            parts = m[1:].split(None, 1)
            expr = parts[1] if len(parts) > 1 else ""
        else:
            parts = m.split(None, 1)
            expr = parts[1] if len(parts) > 1 else ""

    if not expr:
        return (
            "🧮 数学计算器\n"
            "用法: /calc <表达式>  或  计算 <表达式>\n\n"
            "示例:\n"
            "  /calc 1+2*3\n"
            "  /calc sin(pi/4)**2 + cos(pi/4)**2\n"
            "  /calc factorial(100)\n"
            "  /calc hex(255)\n"
            "  /calc frac(22, 7)\n"
            "  /calc mean([1,2,3,4,5])\n"
            "  /calc (1+2j) * (3-4j)\n"
            "  /calc Decimal('0.1') + Decimal('0.2')"
        )

    try:
        evaluator = SafeMathEvaluator()
        result = evaluator.eval(expr)
        return f"🧮 {expr}\n= {format_result(result)}"
    except SyntaxError as e:
        return f"❌ 语法错误: {e.msg}（位置 {e.offset}）"
    except NameError as e:
        return f"❌ {e}"
    except ZeroDivisionError as e:
        return f"❌ 数学错误: {e}"
    except (ValueError, TypeError, OverflowError, RuntimeError) as e:
        return f"❌ 计算错误: {e}"
    except RecursionError as e:
        return f"❌ {e}"
    except Exception as e:
        return f"❌ 未知错误: {type(e).__name__}: {e}"


output = main()