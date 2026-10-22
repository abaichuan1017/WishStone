// Original vector concept illustrations; these are not generated 3D assets.
export function artFor(motif = "cong", id = "art") {
  const prefix = String(id).replace(/[^a-zA-Z0-9-]/g, "");
  const colors = {cong: ["#b7c5ab", "#6f8c71", "#dbe3cd"], bi: ["#b5cbb7", "#6b927e", "#e7eadb"], seed: ["#c7b287", "#94845f", "#eadcba"], bell: ["#a9af8d", "#6e7b5c", "#d3d3a7"], cloud: ["#afb19c", "#6d806a", "#d4d7bb"], lotus: ["#d3bfa5", "#af957b", "#eee0c9"], leaf: ["#a3b694", "#6e8c64", "#dbe2bd"]};
  const c = colors[motif] || colors.cong;
  const fill = `url(#${prefix}-body)`;
  let shape = "";
  if (motif === "cong") {
    shape = `<path d="M73 83Q140 56 207 83L207 202Q140 231 73 202Z" fill="${fill}"/><path d="M73 83L140 106V229L73 202Z" fill="${c[1]}" opacity=".35"/><path d="M140 106L207 83V202L140 229Z" fill="${c[1]}" opacity=".14"/><ellipse cx="140" cy="83" rx="67" ry="25" fill="${c[2]}"/><ellipse cx="140" cy="83" rx="32" ry="12" fill="${c[1]}"/><ellipse cx="140" cy="86" rx="24" ry="8" fill="#365b49" opacity=".6"/><g stroke="${c[2]}" fill="none" stroke-width="3" opacity=".55"><path d="M80 116l50 17m-50 16l50 17m-50 16l50 17M150 133l48-17m-48 50l48-17m-48 50l48-17"/><path d="M88 121v10l32 11v-10m-32 22v10l32 11v-10m36-27v9l33-12v-9m-33 44v9l33-12v-9"/></g>`;
  } else if (motif === "bi") {
    shape = `<ellipse cx="143" cy="159" rx="83" ry="87" fill="${c[1]}"/><path d="M140 65a83 83 0 1 0 0 166 83 83 0 0 0 0-166m0 57a26 26 0 1 1 0 52 26 26 0 0 1 0-52" fill="${fill}" fill-rule="evenodd"/><g fill="none" stroke="${c[2]}" opacity=".6"><circle cx="140" cy="148" r="69"/><circle cx="140" cy="148" r="59"/><circle cx="140" cy="148" r="38"/></g>`;
  } else if (motif === "seed" || motif === "leaf") {
    shape = `<path d="M140 52C223 94 225 179 145 231 60 204 45 107 140 52Z" fill="${fill}"/><path d="M140 69Q122 140 145 217M137 103l-25 11m23 17l-30 13m32 17l-25 14m24-58l31-17m-30 49l38-23m-33 54l29-16" fill="none" stroke="${c[2]}" stroke-width="3" opacity=".65"/><circle cx="140" cy="77" r="5" fill="${c[1]}"/>`;
  } else if (motif === "bell") {
    shape = `<path d="M129 65v-16h22v16M88 89Q140 66 192 89L206 211Q140 240 74 211Z" fill="${fill}" stroke="${c[1]}" stroke-width="4"/><ellipse cx="140" cy="210" rx="63" ry="19" fill="${c[1]}"/><path d="M140 88v113M95 121l31 9m30 0l30-9M93 160l33 10m30 0l32-10" fill="none" stroke="${c[2]}" stroke-width="4"/><g fill="${c[2]}" opacity=".7"><circle cx="110" cy="107" r="4"/><circle cx="171" cy="107" r="4"/><circle cx="106" cy="144" r="4"/><circle cx="174" cy="144" r="4"/><circle cx="102" cy="184" r="4"/><circle cx="178" cy="184" r="4"/></g>`;
  } else if (motif === "lotus") {
    shape = `<path d="M140 226C48 201 61 118 78 99Q123 123 140 182Q157 123 202 99C219 155 221 202 140 226Z" fill="${c[1]}"/><path d="M140 225C80 175 97 100 140 52C183 100 200 175 140 225Z" fill="${fill}"/><path d="M140 74v130M140 226C100 208 84 182 82 140m58 86c40-18 56-44 58-86" stroke="${c[2]}" stroke-width="2" fill="none" opacity=".7"/>`;
  } else {
    shape = `<rect x="71" y="75" width="138" height="148" rx="35" fill="${fill}"/><path d="M100 112h79v24h-57v23h57v28h-79m35-90v105" fill="none" stroke="${c[2]}" stroke-width="7" opacity=".65"/><circle cx="140" cy="88" r="5" fill="${c[1]}"/>`;
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 280 280" fill="none"><defs><linearGradient id="${prefix}-body" x1="65" y1="65" x2="215" y2="230" gradientUnits="userSpaceOnUse"><stop stop-color="${c[2]}"/><stop offset=".45" stop-color="${c[0]}"/><stop offset="1" stop-color="${c[1]}"/></linearGradient></defs>${shape}</svg>`;
}
