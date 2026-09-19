const fs = require('fs');

const classFile = fs.readFileSync('src/WorldScene.js', 'utf8');

// I will just use a simple robust parser since we only need top level class methods
const lines = classFile.split('\n');
let currentMethod = null;
let currentMethodLines = [];
let braceCount = 0;
let inMethod = false;

const methods = new Map();

for (let i = 0; i < lines.length; i++) {
  const line = lines[i];
  
  if (!inMethod) {
    // Match method start like:   async #fetchLiveState(since = 0) {
    // or:   #applyLiveState(payload, { focusClaimedAgent = false, allowTypingFreeze = true } = {}) {
    // or:   constructor() {
    const match = line.match(/^  (async )?([#a-zA-Z0-9_]+)\s*\(/);
    if (match) {
      inMethod = true;
      currentMethod = match[2];
      currentMethodLines = [line];
      braceCount = (line.match(/\{/g) || []).length - (line.match(/\}/g) || []).length;
      
      // If it's a one-liner like `  #foo() { return 1; }`
      if (braceCount === 0 && line.includes('{') && line.includes('}')) {
        methods.set(currentMethod, [...currentMethodLines]);
        inMethod = false;
        currentMethod = null;
      }
    }
  } else {
    currentMethodLines.push(line);
    braceCount += (line.match(/\{/g) || []).length - (line.match(/\}/g) || []).length;
    
    if (braceCount <= 0) {
      methods.set(currentMethod, [...currentMethodLines]);
      inMethod = false;
      currentMethod = null;
    }
  }
}

console.log(`Parsed ${methods.size} methods from WorldScene.js`);

// Dump all method names to a file so I can verify
fs.writeFileSync('method_list.txt', Array.from(methods.keys()).join('\n'));
