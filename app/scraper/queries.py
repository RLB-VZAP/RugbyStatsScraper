"""GraphQL documents used against https://www.unitedrugby.com/graphql."""

# The `clubs` query returns the data-provider's team name ("Edinburgh Rugby"),
# but the site slugs its URLs off `clubThemeSettings.fullName` ("Edinburgh"),
# so we need both and join them on id.
CLUBS = """
query Clubs {
  clubs(limit: 100) {
    id
    team_name
  }
  clubThemeSettings {
    clubs {
      id
      fullName
      shortName
    }
  }
}
"""

# `players` accepts a teamId argument but the resolver ignores it - passing it
# still returns the full league-wide list. We therefore fetch every player once
# and group by the `club_id` on each record.
PLAYERS = """
query Players {
  players {
    id
    club_id
    player_data {
      firstName
      lastName
      knownName
      dob
      # `nationalTeam` is deliberately not requested: its resolver throws
      # "Internal server error" for a chunk of players, which poisons the
      # whole response. Add it back only if the upstream fix lands.
      birthplace
      joinDate
      leaveDate
      height {
        heightM
      }
      weight {
        weightKg
      }
      normalPosition {
        name
      }
      countryOfBirth {
        name
      }
    }
  }
}
"""

# The season dropdown in the player page's nav bar. `excludeFromFilter` names
# the season the site hides from that dropdown (a season that exists in the
# config but isn't offered yet).
SEASONS = """
query Seasons {
  seasonsConfiguration {
    defaultSeasonForRound
    defaultSeasonExceptRound
    excludeFromFilter
    seasons {
      key
      label
    }
  }
}
"""

# The player banner. This is the site's own `GetPlayerThemeSettingsById`.
#
# It is the only source for the banner fields: `players.player_data` has no
# headshot (`media_id` is null for all 897 players) and its `nationalTeam`
# resolver throws. `currentClub` is the club id as a *string*, and the query
# is club-scoped - there is no per-player form, so one player's banner costs
# a whole squad.
#
# `knownName` here is not a display name: it holds the player's URL slug
# ("manuel-rass"), which is the authoritative version of what
# `app/scraper/slugs.py` reconstructs.
PLAYER_SQUAD = """
query PlayerSquad($currentClub: [String]) {
  playerThemeSettings(currentClub: $currentClub) {
    squads {
      currentClub
      squad {
        playerId
        knownName
        playerFirstName
        playerLastName
        playerPosition
        playerAge
        dateOfBirth
        birthcountry
        nationalTeam
        playerHeight
        playerHeightCm
        playerWeight
        headshots
        urcDebut
      }
    }
  }
}
"""

# The stats section. This is the site's own `GetPlayerSeasonStats1`, and the
# field set is exactly what the five panels render.
#
# Two mappings are not obvious:
#   - "Turnovers Lost" (a Defence panel row) is `attack.errors`.
#   - The Attack panel's points/tries come from `scoring`, not `attack`.
#
# `season_id` is typed String on the payload but the *argument* is [Int].
# Passing it is not optional: omitting it returns one row per season the
# player has ever played rather than the current one.
PLAYER_SEASON_STATS = """
query PlayerSeasonStats($playerId: [Int], $seasonId: [Int]) {
  playerseasonstats(player_id: $playerId, season_id: $seasonId) {
    player_id
    season_id
    season_name
    team_id
    team_name
    player_stats {
      playerStats {
        attack {
          carries
          cleanBreak
          defenderBeaten
          metresMade
          offload
          tryAssist
          errors
        }
        defence {
          tackle
          missedTackle
          percentTackleMade
          turnoverWon
        }
        discipline {
          lineoutOffence
          penaltyConceded
          scrumOffence
          yellowCard
          redCard
        }
        kicking {
          kicksInPlay
        }
        lineout {
          lineoutSteals
          lineoutThrowsLost
          lineoutThrowsWon
          percentLineoutsWon
        }
        scoring {
          points
          tryScored
          conversion
          percentGoals
          penaltyGoal
          dropGoal
          appearances
          minutesPlayed
        }
      }
    }
  }
}
"""
