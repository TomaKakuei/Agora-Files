const fs = require('fs');
const classFile = fs.readFileSync('src/WorldScene_new.js', 'utf8');
const lines = classFile.split('\n');

const remaining = new Set();
let inMethod = false;

for (let i = 0; i < lines.length; i++) {
  const line = lines[i];
  if (!inMethod) {
    const match = line.match(/^  (async )?([#a-zA-Z0-9_]+)\s*\(/);
    if (match && !['if', 'for'].includes(match[2])) {
      remaining.add(match[2]);
      inMethod = true;
      let braceCount = (line.match(/\{/g) || []).length - (line.match(/\}/g) || []).length;
      if (braceCount === 0 && line.includes('{') && line.includes('}')) {
        inMethod = false;
      }
    }
  } else {
    let braceCount = (line.match(/\{/g) || []).length - (line.match(/\}/g) || []).length;
    if (braceCount <= 0) {
      inMethod = false;
    }
  }
}

console.log(Array.from(remaining).join('\n'));
