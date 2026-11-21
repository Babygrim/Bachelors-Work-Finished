const weightText = (info) => {
  if (info.parameters == null) return null;
  const count = info.parameters >= 1e6
    ? `${(info.parameters / 1e6).toFixed(2)}M`
    : `${(info.parameters / 1e3).toFixed(0)}K`;
  const parts = [`${info.parameters_estimated ? '≈' : ''}${count} parameters (${info.weight_class.toLowerCase()})`];
  if (info.precision) parts.push(info.precision);
  if (info.size_bytes) parts.push(`${(info.size_bytes / 1e6).toFixed(1)} MB file`);
  return parts.join(' · ');
};

export function modelDisplayName(name, modelInfo) {
  return modelInfo?.[name]?.display || name;
}

export function modelOptions(names, modelInfo) {
  return names.map((name) => new Option(modelDisplayName(name, modelInfo), name));
}

// Lists models only when the names or their descriptions changed (keeps the open dropdown stable).
export function syncModelSelect(select, names, modelInfo) {
  const signature = names.map((name) => modelDisplayName(name, modelInfo)).join('|');
  if (select.dataset.signature === signature) return;
  select.replaceChildren(...modelOptions(names, modelInfo));
  select.dataset.signature = signature;
}

export function renderModelInfo(container, info) {
  container.replaceChildren();
  container.hidden = !info;
  if (!info) return;
  const title = document.createElement('strong');
  title.textContent = info.name;
  container.append(title);
  const rows = [
    ['Weights', weightText(info)],
    ['Architecture', info.architecture],
    ['Used for', info.used_for],
    ['Trained on', info.trained_on],
    ['Complexity', info.complexity],
    ['License', info.license],
  ];
  for (const [label, value] of rows) {
    if (!value) continue;
    const row = document.createElement('p');
    const key = document.createElement('b');
    key.textContent = `${label}: `;
    row.append(key, document.createTextNode(value));
    container.append(row);
  }
}
