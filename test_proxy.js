class WorldScene {
  constructor() {
    this.gridPathingController = new GridPathingController(this);
  }
  syncAgents() {
    console.log("resolve is:", typeof this.gridPathingController.resolveRenderableAgentTile);
  }
}

class GridPathingController {
  constructor(worldScene) {
    this.scene = worldScene;
    return new Proxy(this, {
      get(target, prop) {
        if (prop in target) return target[prop];
        if (prop in worldScene) return typeof worldScene[prop] === 'function' ? worldScene[prop].bind(worldScene) : worldScene[prop];
        return undefined;
      }
    });
  }
  resolveRenderableAgentTile() { return true; }
}

const w = new WorldScene();
w.syncAgents();
