// Captures mouse dynamics (velocity, acceleration, direction changes) by
// sampling mousemove events and reducing them to a small feature vector.

export function createMouseTracker() {
  let points = []; // {x, y, t}
  let lastAngle = null;
  let directionChanges = 0;

  function onMouseMove(e) {
    points.push({ x: e.clientX, y: e.clientY, t: performance.now() });
    if (points.length > 500) points.shift();
  }

  function attach(target) {
    target.addEventListener("mousemove", onMouseMove);
    return () => target.removeEventListener("mousemove", onMouseMove);
  }

  function mean(arr) {
    if (!arr.length) return 0;
    return arr.reduce((a, b) => a + b, 0) / arr.length;
  }

  function std(arr, avg) {
    if (arr.length < 2) return 0;
    const variance = arr.reduce((sum, v) => sum + (v - avg) ** 2, 0) / arr.length;
    return Math.sqrt(variance);
  }

  function snapshot(reset = true) {
    const velocities = [];
    const accelerations = [];
    lastAngle = null;
    directionChanges = 0;
    let lastVelocity = null;

    for (let i = 1; i < points.length; i++) {
      const dx = points[i].x - points[i - 1].x;
      const dy = points[i].y - points[i - 1].y;
      const dt = Math.max(points[i].t - points[i - 1].t, 1);
      const distance = Math.sqrt(dx * dx + dy * dy);
      const velocity = distance / dt;
      velocities.push(velocity);

      if (lastVelocity !== null) {
        accelerations.push((velocity - lastVelocity) / dt);
      }
      lastVelocity = velocity;

      if (distance > 2) {
        const angle = Math.atan2(dy, dx);
        if (lastAngle !== null && Math.abs(angle - lastAngle) > Math.PI / 4) {
          directionChanges += 1;
        }
        lastAngle = angle;
      }
    }

    const meanVelocity = mean(velocities);
    const result = {
      point_count: points.length,
      mean_velocity: meanVelocity,
      std_velocity: std(velocities, meanVelocity),
      mean_acceleration: mean(accelerations),
      direction_changes: directionChanges,
    };

    if (reset) points = [];
    return result;
  }

  function hasEnoughData() {
    return points.length >= 20;
  }

  return { attach, snapshot, hasEnoughData };
}
