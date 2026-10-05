import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { Viewer2D } from "./three/Viewer2D";
import { Viewer3D } from "./three/Viewer3D";
import "./styles.css";

const SAMPLE_NAMES = [
  ["plane", "平面小网格（已是圆盘）"],
  ["cube", "立方体树状切缝"],
  ["closed_tetra", "闭合四面体（非法：无边界）"],
  ["bad_plane_cut", "圆盘被切散（非法见证）"],
];

function normalizeMesh(value) {
  return {
    positions: value.positions.map((p) => p.map(Number)),
    faces: value.faces.map((f) => f.map(Number)),
    seam_edges: (value.seam_edges || []).map((e) => e.map(Number)),
  };
}

function downloadJson(filename, value) {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export default function App() {
  const viewer3dRef = useRef(null);
  const viewer2dRef = useRef(null);
  const container3d = useRef(null);
  const container2d = useRef(null);

  const [mesh, setMesh] = useState(null);
  const [preparation, setPreparation] = useState(null);
  const [solution, setSolution] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [sampleName, setSampleName] = useState("plane");
  const [anchorMode, setAnchorMode] = useState(false);
  const [anchor0, setAnchor0] = useState("");
  const [anchor1, setAnchor1] = useState("");
  const [selectedFace, setSelectedFace] = useState(null);
  const [jsonText, setJsonText] = useState("");
  const handle3DPickRef = useRef(null);

  useEffect(() => {
    viewer3dRef.current = new Viewer3D(container3d.current, (pick) => handle3DPickRef.current?.(pick));
    viewer2dRef.current = new Viewer2D(container2d.current, (faceId) => setSelectedFace(faceId));
    return () => {
      viewer3dRef.current = null;
      viewer2dRef.current = null;
    };
  }, []);

  async function loadSample(name = sampleName) {
    setBusy(true);
    setError("");
    try {
      const loaded = normalizeMesh(await api.sample(name));
      setSampleName(name);
      setMesh(loaded);
      resetResults();
      setSelectedFace(null);
      viewer3dRef.current?.setMesh(loaded);
      await runPrepare(loaded);
    } catch (exc) {
      setError(exc.message);
    } finally {
      setBusy(false);
    }
  }

  function resetResults() {
    setPreparation(null);
    setSolution(null);
    setAnchorMode(false);
    setAnchor0("");
    setAnchor1("");
  }

  useEffect(() => {
    loadSample("plane");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function runPrepare(currentMesh = mesh) {
    if (!currentMesh) return;
    setBusy(true);
    setError("");
    setSolution(null);
    try {
      const prep = await api.prepare(currentMesh);
      setPreparation(prep);
      viewer3dRef.current?.setPreparation(prep);
      viewer3dRef.current?.setAnchors(anchorsForRequest(prep), prep);
      if (!prep.valid_for_solve) setAnchorMode(false);
    } catch (exc) {
      setPreparation(null);
      setError(exc.message);
    } finally {
      setBusy(false);
    }
  }

  function anchorsForRequest(prepValue = preparation) {
    const anchors = [];
    if (anchor0 !== "") anchors.push({ vertex: Number(anchor0), uv: [0, 0] });
    if (anchor1 !== "") anchors.push({ vertex: Number(anchor1), uv: [1, 0] });
    if (anchors.length === 2 && prepValue) return anchors;
    return [];
  }

  function handlePick3D(pick) {
    if (pick.type === "face") {
      setSelectedFace(pick.faceId);
      return;
    }
    if (pick.type === "seam") {
      const [a, b] = pick.edge;
      setMesh((current) => {
        if (!current) return current;
        const exists = current.seam_edges.some(([x, y]) => x === a && y === b);
        const seam_edges = exists
          ? current.seam_edges.filter(([x, y]) => !(x === a && y === b))
          : [...current.seam_edges, [a, b]].sort((x, y) => x[0] - y[0] || x[1] - y[1]);
        const next = { ...current, seam_edges };
        viewer3dRef.current?.setMesh(next, false);
        queueMicrotask(() => runPrepare(next));
        return next;
      });
      return;
    }
    if (pick.type === "anchor") {
      if (!anchor0) setAnchor0(String(pick.chartVertex));
      else if (!anchor1) setAnchor1(String(pick.chartVertex));
      else setAnchor0(String(pick.chartVertex));
    }
  }

  useEffect(() => {
    handle3DPickRef.current = handlePick3D;
  });

  useEffect(() => {
    const anchors = anchorsForRequest();
    viewer3dRef.current?.setAnchors(anchors, preparation);
  }, [anchor0, anchor1, preparation]);

  useEffect(() => {
    viewer3dRef.current?.setSelectedFace(selectedFace);
    viewer2dRef.current?.setSelectedFace(selectedFace);
  }, [selectedFace, solution]);

  useEffect(() => {
    viewer3dRef.current?.setAnchorPickMode(anchorMode);
  }, [anchorMode, preparation]);

  async function solve() {
    if (!preparation?.valid_for_solve) {
      setError(preparation?.witness?.message || "当前切口不是一个拓扑圆盘，不能求解。");
      return;
    }
    if (anchor0 === "" || anchor1 === "" || anchor0 === anchor1) {
      setError("请选择两个不同的拆分后边界顶点作为锚点。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await api.solve(mesh, [
        { vertex: Number(anchor0), uv: [0, 0] },
        { vertex: Number(anchor1), uv: [1, 0] },
      ]);
      setSolution(result);
      viewer3dRef.current?.setSolution(result, mesh);
      viewer2dRef.current?.setResult(result);
      setSelectedFace(0);
      if (!result.ok) {
        setError(result.warnings.join("；") || "求解结果无效。");
      }
    } catch (exc) {
      setError(exc.message);
    } finally {
      setBusy(false);
    }
  }

  function loadCustomJson() {
    try {
      const parsed = JSON.parse(jsonText);
      const loaded = normalizeMesh(parsed);
      if (!Array.isArray(loaded.positions) || !Array.isArray(loaded.faces)) throw new Error("缺少 positions 或 faces");
      setMesh(loaded);
      resetResults();
      setSelectedFace(null);
      viewer3dRef.current?.setMesh(loaded);
      runPrepare(loaded);
    } catch (exc) {
      setError(`JSON 无效：${exc.message}`);
    }
  }

  const selectedMetric = solution?.faces?.[selectedFace];
  const selectedCorners = solution?.face_corner_uv?.filter((c) => c.face_id === selectedFace) || [];
  const boundaryOptions = preparation?.chart_vertices?.filter((v) => v.boundary) || [];

  const stats = useMemo(() => {
    if (!preparation) return null;
    return {
      V: preparation.original_vertex_count,
      Vuv: preparation.chart_vertex_count,
      F: preparation.triangle_count,
      E: preparation.edge_count,
      b: preparation.boundary_loop_count,
      chi: preparation.euler_characteristic,
    };
  }, [preparation]);

  return (
    <div className="app">
      <header>
        <div>
          <h1>小网格 LSCM UV 展开工具</h1>
          <p>最多 200 个三角形；按面片扇区拆分，手工指定切缝与两个边界锚点。</p>
        </div>
        <div className="sample-row">
          <select value={sampleName} onChange={(e) => loadSample(e.target.value)}>
            {SAMPLE_NAMES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <button onClick={() => runPrepare()}>重新检查切缝</button>
        </div>
      </header>

      <main>
        <section className="viewers">
          <div className="panel viewer-panel">
            <div className="panel-title">
              <h2>三维模型</h2>
              <span>Shift+点击红边切换切缝</span>
            </div>
            <div ref={container3d} className="canvas-container" />
          </div>
          <div className="panel viewer-panel">
            <div className="panel-title">
              <h2>二维 LSCM 与棋盘纹理</h2>
              <span>点击三角形定位同一原面</span>
            </div>
            <div ref={container2d} className="canvas-container" />
          </div>
        </section>

        <aside className="panel controls">
          <h2>拓扑与锚点</h2>
          {error && <div className="error">{error}</div>}
          {busy && <div className="notice">正在处理…</div>}

          {preparation && (
            <div className={`topology ${preparation.valid_for_solve ? "good" : "bad"}`}>
              <strong>{preparation.valid_for_solve ? "切开后是一个拓扑圆盘" : "拒绝求解：不是一个拓扑圆盘"}</strong>
              <div>V={stats.V}，UV扇区V*={stats.Vuv}，F={stats.F}，E={stats.E}，边界环={stats.b}，χ={stats.chi}</div>
              {preparation.witness && (
                <details open>
                  <summary>边界/连通见证</summary>
                  <pre>{JSON.stringify(preparation.witness, null, 2)}</pre>
                </details>
              )}
              {preparation.valid_for_solve && (
                <details>
                  <summary>查看唯一边界环（拆分后 ID）</summary>
                  <pre>{JSON.stringify(preparation.boundary_loops[0]?.chart_vertices, null, 2)}</pre>
                </details>
              )}
            </div>
          )}

          <div className="button-row">
            <button disabled={!preparation?.valid_for_solve} onClick={() => setAnchorMode((v) => !v)}>
              {anchorMode ? "结束锚点选择" : "选择边界锚点"}
            </button>
            <button onClick={() => { setAnchor0(""); setAnchor1(""); }}>清空</button>
            <button disabled={!preparation?.valid_for_solve} onClick={solve}>组装并求解 LSCM</button>
          </div>

          <label>
            锚点 A 固定 (0,0)
            <select value={anchor0} onChange={(e) => setAnchor0(e.target.value)}>
              <option value="">未选择</option>
              {boundaryOptions.map((v) => (
                <option key={v.id} value={v.id}>UV顶点 {v.id} / 原顶点 {v.original_vertex}</option>
              ))}
            </select>
          </label>
          <label>
            锚点 B 固定 (1,0)
            <select value={anchor1} onChange={(e) => setAnchor1(e.target.value)}>
              <option value="">未选择</option>
              {boundaryOptions.map((v) => (
                <option key={v.id} value={v.id}>UV顶点 {v.id} / 原顶点 {v.original_vertex}</option>
              ))}
            </select>
          </label>
          <p className="hint">三维中青色球代表切缝后的边界扇区；相同三维坐标也可能是不同 UV 身份。</p>

          {solution && (
            <div className={`solution ${solution.ok ? "good" : "bad"}`}>
              <h3>求解报告</h3>
              <div>状态：{solution.status}</div>
              <div>矩阵：{solution.summary.matrix_shape.join(" × ")}</div>
              <div>秩：{solution.summary.rank} / 期望 {solution.summary.expected_rank}</div>
              <div>残差范数：{solution.summary.residual_norm.toExponential(4)}</div>
              <div>RMS 行残差：{solution.summary.residual_rms.toExponential(4)}</div>
              <div>最大角度误差：{solution.summary.max_angle_error_deg == null ? "退化，不可用" : `${solution.summary.max_angle_error_deg.toFixed(5)}°`}</div>
              <div>翻转面：{solution.summary.flipped_face_ids.length ? solution.summary.flipped_face_ids.join(", ") : "无"}</div>
              <div>退化面：{solution.summary.degenerate_uv_face_ids.length ? solution.summary.degenerate_uv_face_ids.join(", ") : "无"}</div>
              <button onClick={() => downloadJson("lscm-face-corner-uv.json", {
                face_corner_uv: solution.face_corner_uv,
                summary: solution.summary,
              })}>导出每面角 UV + 原面 ID</button>
            </div>
          )}

          {selectedMetric && (
            <div className="face-report">
              <h3>原面 {selectedFace} / UV 面 {selectedFace}</h3>
              <div>最大角误差：{selectedMetric.max_angle_error_deg == null ? "退化，不可用" : `${selectedMetric.max_angle_error_deg.toFixed(5)}°`}</div>
              <div>共形残差：{selectedMetric.conformal_residual.toExponential(4)}</div>
              <div>有向 UV 面积：{selectedMetric.signed_uv_area.toFixed(6)}</div>
              <div>面积比：{selectedMetric.area_ratio == null ? "不可用" : Number(selectedMetric.area_ratio).toFixed(5)}</div>
              <table>
                <thead><tr><th>角</th><th>原顶点</th><th>UV顶点</th><th>角度误差</th></tr></thead>
                <tbody>
                  {selectedCorners.map((c) => (
                    <tr key={`${c.face_id}-${c.corner}`}>
                      <td>{c.corner}</td>
                      <td>{c.original_vertex}</td>
                      <td>{c.chart_vertex}</td>
                      <td>{c.angle_error_deg == null ? "退化" : `${c.angle_error_deg.toFixed(4)}°`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <details className="json-loader">
            <summary>导入自定义 JSON 网格</summary>
            <textarea value={jsonText} onChange={(e) => setJsonText(e.target.value)} placeholder='{"positions":[[0,0,0],...],"faces":[[0,1,2],...],"seam_edges":[[0,1]]}' />
            <button onClick={loadCustomJson}>加载</button>
          </details>
        </aside>
      </main>
    </div>
  );
}
