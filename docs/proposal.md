# TravAI — Project Proposal

> Source of truth for scope, ownership and acceptance examples. Text is as submitted, except that names are reduced to first names because this repository is public.

**Group name:** TravAI

## Who owns what

### Jake
- **What they're doing:** The backend and planner agent.
- **What done means:** The backend, API routes, and planner agent are all complete to the specs described below. This can be checked by other team members by running a test prompt on the planner agent with dummy data or real data from the research agent when it is complete.
- **What is needed from other parts:** To test the planner agent fully I will need the research agent finished, although I can use example data to test it before then. I will need to connect the web app backend to the frontend UI in order to fully test all of its functionality.

### Fernando
- **What they're doing:** Front-end user interface and its features.
- **What done means:** The web app works how it was described in this proposal.
- **What is needed from other parts:** The backend so that it can send the information the user gives it to the agents, and so that it can display the results of the research.

### Kyle
- **What they're doing:** Research Agent and associated tools.
- **What done means:** The research agent is able to successfully find and verify information such as flight and place of interest data that is rich enough that it can be used by the planner.
- **What is needed from other parts:** Nothing, this will be necessary for the other parts.

## Our user and their problem

The primary test user for this project will be Kyle from the group. The goal product would be a travel app that has a practical application in helping plan and coordinate travel plans. Since traveling costs can vary considerably depending on many external factors, it can be difficult and time consuming to plan a trip. Therefore, the goal of this application is to use agentic tools to perform online research and create travel plans that fall around a given budget. Since trips to other countries are typically more expensive, this application will be designed with larger foreign trips in mind. However, the application needs to stay grounded in reality. It should not underestimate costs, as this creates distrust and undermines its purpose. How often this application is used is entirely reliant on how often users are planning trips. Considering that this application is primarily designed for foreign trips, Kyle estimates using this tool only a couple times a year. The user experience is expected to involve choosing a travel destination and a budget. From there the application should provide options for the user so they are still able to customize their own vacation for themselves. This would be a dramatic improvement over how the user currently plans trips. As of now, the user tediously seeks out flights and destinations, planning each part of the trip independently. This process can be frustrating and confusing and takes hours of research and coordination. Additionally, it's difficult to determine whether or not the user is receiving a good deal leading to potential unnecessary expenses.

## What we will build

We are building a travel web app which will allow a user to enter a destination, trip duration, and their budget to get three plans to choose from or edit. It will use AI agents to research the destination, find the price of activities and amenities, and plan three potential itineraries for the trip. We are going to build the web app using Next.js, a React frontend, and a Python/FastAPI backend with a Postgres database for caching search results with the important information the planner agent needs.

There will be two AI agents in this project, the first is a research agent which will find flights, amenities, and activities with their prices and source links. The second is the planner which will take the research agent's output and check the budget, hours, and travel time to build three itineraries or tell the user that the trip is impossible with their current budget. If the plan is edited by the user, it will be sent back to the planner agent to be redrafted based on their edits. The reason this needs to use agents is that there are far too many edge cases and important value judgements that traditional software would be unable to make. A fixed workflow would be unable to pick out the best search results as effectively as an agent and it would be nearly impossible to write enough rules to get it to consistently create effective plans. It cannot be a single prompt because the agents need to make multiple searches and adjust said searches based on the information it found. The agents need to decide what to search next based on their initial information and anything they find while researching, when there are enough options to stop searching, what to add or drop based on the budget and schedule, and how to change the plan to fit with a user's edit. It is better to use two agents because the planner agent doesn't need the entire context from the research agent, it only needs the important information it adds to the database.

### Walkthrough of the first example from the appendix, a trip to Japan with a $5,000 budget

1. **Kyle types his home airport, Tokyo as his destination, a travel duration of 5 days, 1 traveler, and a $5,000 budget, then clicks "Plan my trip."**
2. **The research agent gets to work.** A progress screen shows what it's doing, such as "Found 4 flights, checking hotel prices" and "Found 30 activities." The agent saves each option, with its price and source link, to the database.
3. **The planner builds three itineraries.** It reads the saved options and creates three different plans, for example "Temples and history," "Food and nightlife," and "Day trips." Each plan includes a flight, a hotel, a day-by-day schedule, and a cost breakdown.
4. **Kyle compares the plans.** They appear side by side, each showing its total against the $5,000 budget. He picks "Temples and history."
5. **Kyle edits the plan.** He removes a tea ceremony, adds a day trip to Mount Fuji from the list of other options, and moves the Senso-ji temple visit from day 3 to day 1. The running total updates as he goes.
6. **The planner redrafts.** Kyle clicks "Redraft." The planner keeps his changes and adjusts the rest of the schedule to fit. If the Mount Fuji trip pushes the total over budget, it shows what it dropped to stay under.
7. **Kyle saves the plan and can come back to it later.**

## Plan to Dec 3

| Week  | Kyle | Jake | Fernando |
|-------|------|------|----------|
| 11/9  | Research and create a plan about what research tools exist already and how accessible they are. | Create the initial Python/FastAPI backend with a Postgres database | Initial set up for the Next.js project, including the GitHub repository |
| 11/16 | Creating and testing the research process, looking for significant gaps. | Implement the search caching system. Work on the basic implementation of the planner agent. | Create the initial front-end with React |
| 11/23 | Adjusting and fixing the research based on feedback and dependencies from the other developers. | Finish the planner agent. Functionality testing, verify all features work | Finalize UI and backend features |
| 11/30 | Work on presentation | Work on presentation | Work on presentation |

The first end-to-end version will be done by Nov 25th. The group presentations happen on Dec 3 and 8, so the user will try the application on Nov 29 and the last week will be spent working on the presentation.

## Risks

Since this process requires high precision from the agents and the research there are several risks which could impact the development process. The largest risks are:

- Travel data can quickly become outdated which could severely impact pricing and availability
- Budget monitoring/adjusting becoming too complex for an agent
- API costs/availability for performing travel research

We may have to cut some features due to time constraints or other reasons. If this happens, some non-essential features we can cut are:

- Dangerous area warnings
- Cross country itineraries
- Travel customization features

## Appendix examples

1. **Tokyo, 5 days, $5,000.** The user wants to plan a trip to Japan, so they use the application and input a 5 day trip to Tokyo with a budget of $5000. The user should then be shown 3 unique itineraries that provide various activities and attractions in Tokyo that fall under or at their budget. From here, ideally they could still customize their trip by adding or dropping things while their current budget stays up to date.
2. **Colorado Springs, 1 day, $500.** The user wants to take a day trip to Colorado Springs. The user uses the UI to select Colorado Springs, 1 day and a budget of $500. Since the user doesn't need a flight and can drive this should be selectable as an option. The application then finds activities to do during the day for the user that fall under their budget.
3. **Europe, 2 weeks, $10,000.** The user wants to take a 2 week trip across Europe. The user enters this information and their budget of $10,000. Since this trip is more vague, the user will specify a starting point and potentially an end destination. From here the application should find activities for their trip that make sense chronologically. Additionally, the application should find a route between stops using available map data for the trip to follow.
4. **Japan, 1 month, $500.** The user wants to take a trip to Japan for a month with a $500 budget. After the user enters this information the application should report honestly that this is likely impossible given their budget. The application should never underestimate costs as this could derail a trip entirely and potentially leave the user stranded.
5. **Ukraine, 3 days, $1,000 (hard case).** The user wants to take a trip to Ukraine for 3 days with their budget of $1,000. The application should report that this could be potentially dangerous as the map data could be outdated, given the state of the destination. From here the application should let the user proceed if they wish. It should then provide the same user experience as other destinations where 3 itineraries are provided where the app assumes that the map data that it uses is correct. This is our hard case because the obvious answer would be to just answer the request instead of starting with a warning.
