#!/usr/bin/env node

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

import { callBridge } from "./bridge.js";

const server = new McpServer({
  name: "skillroute",
  version: "0.1.0"
});

const routeSchema = {
  request: z.string().min(1).describe("User request or task to route to skills."),
  repo: z.string().optional().describe("Optional repository path for lightweight context signals."),
  catalog: z.string().optional().describe("Optional SkillRoute SQLite catalog path."),
  limit: z.number().int().min(1).max(20).optional().describe("Maximum number of ranked skills.")
};

const searchSchema = {
  query: z.string().min(1).describe("Search query for the skill catalog."),
  catalog: z.string().optional().describe("Optional SkillRoute SQLite catalog path."),
  limit: z.number().int().min(1).max(50).optional().describe("Maximum number of results.")
};

const inspectSchema = {
  skill_id: z.string().min(1).describe("Skill id or exact skill name to inspect."),
  catalog: z.string().optional().describe("Optional SkillRoute SQLite catalog path.")
};

server.registerTool(
  "skillroute.route",
  {
    title: "Route to Skills",
    description:
      "Return ranked skills, reasons, confidence, evidence snippets, suggested order, and clarification questions.",
    inputSchema: routeSchema
  },
  async (args) => {
    const result = await callBridge("route", args);
    return jsonContent(result);
  }
);

server.registerTool(
  "skillroute.search",
  {
    title: "Search Skills",
    description: "Search indexed skills using hybrid metadata, lexical, and local semantic signals.",
    inputSchema: searchSchema
  },
  async (args) => {
    const result = await callBridge("search", args);
    return jsonContent(result);
  }
);

server.registerTool(
  "skillroute.inspect_skill",
  {
    title: "Inspect Skill",
    description: "Fetch metadata, relationships, excerpts, and source references for one skill.",
    inputSchema: inspectSchema
  },
  async (args) => {
    const result = await callBridge("inspect", args);
    return jsonContent(result);
  }
);

function jsonContent(value: unknown) {
  return {
    content: [
      {
        type: "text" as const,
        text: JSON.stringify(value, null, 2)
      }
    ]
  };
}

const transport = new StdioServerTransport();
await server.connect(transport);

